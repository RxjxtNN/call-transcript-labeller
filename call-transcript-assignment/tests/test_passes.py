import json
from unittest import TestCase

from helpers import call, response
from unittest.mock import patch

from labeler.finalize import finalize_prediction, merge_follow_up
from labeler.passes import second_pass
from labeler.transcript import callback_candidates, dialogue_turns, quoted_in

POSTPONED = "Agent: It costs 1000.\nCustomer: That is costly.\nAgent: Shall we book?\nCustomer: No, I'll see, I need some time."


def second(label, turn, quote, postponement=None, callback=None):
    return {"final_reason": {"label": label, "turn": turn, "quote": quote},
            "postponement": postponement or {"present": False, "turn": None, "quote": ""},
            "callback": callback or response()["callback"]}


class TranscriptTests(TestCase):
    def test_candidates_find_timed_offers_with_replies(self):
        turns = dialogue_turns("Agent: Should I call you next week?\nCustomer: Yes, call in between.\n"
                               "Agent: Send me reports, I will tell you in 15 minutes.\nCustomer: Okay, okay.\n"
                               "Agent: The clinic opens at 10 am.\nCustomer: Fine.")
        self.assertEqual(callback_candidates(turns), [(1, 2), (3, 4)])

    def test_quotes_tolerate_punctuation_and_ok(self):
        self.assertTrue(quoted_in("Ok, okay.", "Okay, okay."))
        self.assertFalse(quoted_in("Yes, please book it.", "Great."))

    def test_excerpt_keeps_tail_and_cited_turns_with_gap_markers(self):
        record = call("\n".join(f"Customer: line {n}" for n in range(1, 41)))
        first = response()
        first["follow_up"]["reason_turn"] = 2
        answer = {"final_reason": {}, "postponement": {}, "callback": {}}
        with patch("labeler.passes.send_model", return_value=(answer, {})) as send:
            second_pass(record, dialogue_turns(record["transcript"]), "gemini/x", "rules", first, {})
        turns_text = json.loads(send.call_args.args[2])["turns"]
        self.assertTrue(turns_text.startswith("2 customer: line 2\n...\n11 customer: line 11"))
        self.assertTrue(turns_text.endswith("40 customer: line 40"))


class MergeTests(TestCase):
    def test_grounded_final_reason_replaces_first_pass_blocker(self):
        record = call(POSTPONED)
        first = response(blockers=["Cost Concern"])
        prediction, _ = finalize_prediction(record, merge_follow_up(record, first, second("Vague Deferral", 4, "I need some time")))
        self.assertEqual((prediction["sub_disposition"], prediction["next_call_at"]),
                         ("Vague Deferral", "2026-11-12T11:00:00+05:30"))
        ungrounded = second("Vague Deferral", 4, "made-up words")
        # An uncited first-pass blocker does not survive an ungrounded second pass (AVT-015 pattern)...
        self.assertEqual(finalize_prediction(record, merge_follow_up(record, first, ungrounded))[0]["sub_disposition"],
                         "Further Discussion")
        # ...but a first-pass blocker that cites a real turn does.
        first["follow_up"]["reason_turn"] = 2
        self.assertEqual(finalize_prediction(record, merge_follow_up(record, first, ungrounded))[0]["sub_disposition"],
                         "Cost Concern")

    def test_first_pass_callback_survives_when_second_pass_finds_none(self):
        # Demo-call pattern: the first pass found "Call tomorrow at four?" / "Okay, I'll call tomorrow at four.",
        # the second pass returned no agreement. The grounded first-pass callback must not be dropped.
        from helpers import agreed, demo_call, option
        record = demo_call()
        first = response(blockers=["Cost Concern"], callback=agreed(
            1, "Call tomorrow at four?", 2, "Okay, I'll call tomorrow at four.", option("days", 1, "16:00", "tomorrow at four")))
        answer = second("Cost Concern", 1, "afford the fee")
        prediction, _ = finalize_prediction(record, merge_follow_up(record, first, answer))
        self.assertEqual((prediction["sub_disposition"], prediction["next_call_at"]),
                         ("Cost Concern", "2026-11-10T16:00:00+05:30"))

    def test_blocker_keeps_label_while_postponement_sets_three_day_fallback(self):
        record = call("Agent: Shall we book?\nCustomer: I will consult my wife and let you know.")
        answer = second("Family Discussion", 2, "consult my wife", {"present": True, "turn": 2, "quote": "let you know"})
        prediction, rule = finalize_prediction(record, merge_follow_up(record, response(), answer))
        self.assertEqual((prediction["sub_disposition"], prediction["next_call_at"]),
                         ("Family Discussion", "2026-11-12T11:00:00+05:30"))
        self.assertIn("F7", rule)

    def test_final_reason_must_be_the_callers_and_postponement_must_be_quoted(self):
        record = call("Agent: I will share the details on WhatsApp.\nCustomer: Cost is too much for me right now.\n"
                      "Agent: Okay sir, you can let me know.")
        # The agent's sentence is not the caller's reason (AVT-041 pattern), so the first pass's cited blocker stays.
        first = response(blockers=["Cost Concern"])
        first["follow_up"]["reason_turn"] = 2
        agent_reason = second("Information Requested", 1, "share the details on WhatsApp")
        self.assertEqual(finalize_prediction(record, merge_follow_up(record, first, agent_reason))[0]["sub_disposition"],
                         "Cost Concern")
        # The agent restating the caller's deferral counts for F7 (AVT-019 pattern); an unquoted one does not.
        restated = second("Cost Concern", 2, "Cost is too much", {"present": True, "turn": 3, "quote": "you can let me know"})
        self.assertEqual(finalize_prediction(record, merge_follow_up(record, first, restated))[0]["next_call_at"],
                         "2026-11-12T11:00:00+05:30")
        invented = second("Cost Concern", 2, "Cost is too much", {"present": True, "turn": 3, "quote": "call me next year"})
        self.assertEqual(finalize_prediction(record, merge_follow_up(record, first, invented))[0]["next_call_at"],
                         "2026-11-10T11:00:00+05:30")
