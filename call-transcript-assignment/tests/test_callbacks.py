from unittest import TestCase

from helpers import agreed, call, option, response
from labeler.callbacks import call_time, callback_time, normalize_timing
from labeler.finalize import finalize_prediction


def follow_up(options=(), vague=False):
    return {"options": list(options), "vague_postponement": vague}


class CalendarTests(TestCase):
    def test_each_timing_kind_resolves_against_the_call_start(self):
        cases = [  # F4, F5, F6, F10, F11
            ("2026-11-09T14:00:32+05:30", "days", 1, "16:00", "2026-11-10T16:00:00"),
            ("2026-11-09T14:00:32+05:30", "weekday", 0, "17:00", "2026-11-16T17:00:00"),
            ("2026-11-09T14:00:32+05:30", "this_weekday", 0, "17:00", "2026-11-09T17:00:00"),
            ("2026-11-09T14:00:32+05:30", "next_weekday", 4, None, "2026-11-20T11:00:00"),
            ("2026-11-09T14:00:32+05:30", "next_week", None, None, "2026-11-16T11:00:00"),
            ("2026-11-09T14:00:32+05:30", "clock", None, "13:00", "2026-11-10T13:00:00"),
            ("2026-11-09T14:00:32+05:30", "minutes", 90, None, "2026-11-09T15:30:32"),
            ("2026-01-31T14:00:32+05:30", "months", 1, None, "2026-02-28T11:00:00"),
            ("2026-01-31T14:00:32+05:30", "next_month", None, None, "2026-02-01T11:00:00"),
            ("2026-11-09T14:00:32+05:30", "month_day", "11-09", None, "2027-11-09T11:00:00"),
            ("2026-11-09T14:00:32+05:30", "date", "2026-11-09", "13:00", "2026-11-10T11:00:00"),  # past -> F8
        ]
        for start, kind, value, clock, expected in cases:
            with self.subTest(kind=kind):
                callback = follow_up([{"kind": kind, "value": value, "clock": clock}])
                target, _, _ = callback_time(call_time(start), "Follow-up Required", callback)
                self.assertEqual(target.isoformat(), expected + "+05:30")

    def test_suppression_earliest_alternative_and_fallbacks(self):
        start = call_time("2026-11-09T14:00:00+05:30")
        callback = follow_up([{"kind": "days", "value": n, "clock": "16:00"} for n in (3, 1)])
        for disposition in ("Not Interested", "Invalid Lead", "Unable to Assess"):  # F2
            self.assertIsNone(callback_time(start, disposition, callback)[0])
        self.assertEqual(callback_time(start, "Appointment Scheduled", callback)[0].isoformat(),
                         "2026-11-10T16:00:00+05:30")  # F3/F10: earliest accepted alternative
        self.assertIsNone(callback_time(start, "Appointment Scheduled", follow_up())[0])  # F8
        self.assertEqual(callback_time(start, "Follow-up Required", follow_up(vague=True))[0].isoformat(),
                         "2026-11-12T11:00:00+05:30")  # F7
        broken = follow_up([{"kind": "days", "value": None, "clock": None}])
        self.assertEqual(callback_time(start, "Follow-up Required", broken)[0].isoformat(),
                         "2026-11-10T11:00:00+05:30")  # A malformed option falls back to F8.

    def test_quoted_phrase_overrides_model_encoding(self):
        for phrase, expected in [("this evening", ("days", 0, "18:00")), ("wednesday", ("weekday", 2, None)),
                                 ("next friday", ("next_weekday", 4, None))]:
            with self.subTest(phrase=phrase):
                fixed = normalize_timing({"kind": "weekday", "value": 3, "clock": None}, phrase)
                self.assertEqual((fixed["kind"], fixed["value"], fixed["clock"]), expected)


class GroundingTests(TestCase):
    def test_acknowledgment_must_be_later_and_from_the_other_speaker(self):
        record = call("Customer: Okay.\nAgent: I will call tomorrow afternoon.\nAgent: Okay.\nCustomer: Okay.")
        callback = agreed(2, "I will call tomorrow afternoon", 4, "Okay.",
                          option("days", 1, "12:00", "tomorrow afternoon"))
        prediction, _ = finalize_prediction(record, response(callback=callback))
        self.assertEqual((prediction["next_call_at"], prediction["sub_disposition"]),
                         ("2026-11-10T15:00:00+05:30", "Specific Callback"))  # 'afternoon' -> 15:00
        for bad_turn in (1, 3, 99):
            with self.subTest(acknowledgment_turn=bad_turn):
                callback["agreement"]["acknowledgment_turn"] = bad_turn
                prediction, rule = finalize_prediction(record, response(callback=callback))
                self.assertEqual(prediction["next_call_at"], "2026-11-10T11:00:00+05:30")
                self.assertIn("discarded", rule)

    def test_blocker_owns_label_while_agreed_evening_callback_sets_time(self):
        record = call("Customer: I work today. Call me this evening.\nAgent: Okay.")
        callback = agreed(1, "Call me this evening", 2, "Okay", option("days", 0, None, "this evening"))
        prediction, _ = finalize_prediction(record, response(blockers=["Travel Constraint"], callback=callback))
        self.assertEqual((prediction["sub_disposition"], prediction["next_call_at"]),
                         ("Travel Constraint", "2026-11-09T18:00:00+05:30"))

    def test_clarification_request_is_not_an_acknowledgment(self):
        record = call("Agent: We will take a follow-up call from you on Wednesday.\nCustomer: Pardon?")
        callback = agreed(1, "follow-up call from you on Wednesday", 2, "Pardon?", option("weekday", 2, None, "Wednesday"))
        prediction, rule = finalize_prediction(record, response(callback=callback))
        self.assertEqual(prediction["next_call_at"], "2026-11-10T11:00:00+05:30")  # F8, not Wednesday
        self.assertIn("discarded", rule)

    def test_acknowledgment_must_answer_the_proposal_not_a_later_question(self):
        # AVT-041 pattern: a 'yes' several turns later answers a different question.
        record = call("Agent: We will call you on Wednesday.\nCustomer: Pardon?\nAgent: Your name?\nCustomer: Dev.\n"
                      "Agent: Is this number on WhatsApp?\nCustomer: Yes, everything is on this number.")
        callback = agreed(1, "We will call you on Wednesday", 6, "Yes, everything is on this number",
                          option("weekday", 2, None, "Wednesday"))
        self.assertEqual(finalize_prediction(record, response(callback=callback))[0]["next_call_at"],
                         "2026-11-10T11:00:00+05:30")

    def test_tolerant_quote_accepts_ok_for_okay(self):
        record = call("Agent: I will tell you in 15 minutes.\nCustomer: Okay, okay.", start="2026-10-15T14:11:01+05:30")
        callback = agreed(1, "I will tell you in 15 minutes", 2, "Ok, okay.", option("minutes", 15, None, "in 15 minutes"))
        self.assertEqual(finalize_prediction(record, response(callback=callback))[0]["next_call_at"],
                         "2026-10-15T14:26:01+05:30")  # F10 keeps the seconds.
