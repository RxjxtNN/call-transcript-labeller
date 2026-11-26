from unittest import TestCase

from helpers import call, response
from labeler.decisions import derive_quality
from labeler.finalize import finalize_prediction

BOOKED = ("Agent: Shall I book a clinic visit tomorrow at two?\nCustomer: Yes, book it.\n"
          "Customer: Actually no, I'll cancel the appointment, thank you.")
CONFIRMED = {"confirmed": True, "child": "Clinic Visit", "turn": 2, "quote": "Yes, book it."}


def labels(record, answers):
    prediction, rule = finalize_prediction(record, answers)
    return prediction["disposition"], prediction["sub_disposition"], prediction["lead_quality"], rule


class PrecedenceTests(TestCase):
    """D6: Invalid Lead > Not Interested > Appointment Scheduled > Follow-up Required > Unable to Assess."""

    def test_grounded_invalid_reason_wins_and_ungrounded_is_ignored(self):
        record = call("Agent: How can I help?\nCustomer: This is just a test call from your IT team.")
        invalid = {"reason": "Test Enquiry", "turn": 2, "quote": "just a test call"}
        self.assertEqual(labels(record, response(invalid=invalid))[:3], ("Invalid Lead", "Test Enquiry", "Not Qualified"))
        invalid["quote"] = "words that were never said"
        self.assertEqual(labels(record, response(invalid=invalid))[0], "Follow-up Required")

    def test_final_refusal_beats_an_earlier_booking(self):
        refusal = {"kind": "Explicit Refusal", "turn": 3, "quote": "I'll cancel the appointment"}
        self.assertEqual(labels(call(BOOKED), response(refusal=refusal, booking=CONFIRMED))[:3],
                         ("Not Interested", "Explicit Refusal", "Low"))

    def test_later_booking_supersedes_an_earlier_refusal(self):
        record = call("Customer: No, I don't want it.\nAgent: Shall I book a clinic visit tomorrow at two?\n"
                      "Customer: Okay fine, yes, book it.")
        refusal = {"kind": "Explicit Refusal", "turn": 1, "quote": "I don't want it"}
        booking = {**CONFIRMED, "turn": 3, "quote": "yes, book it"}
        self.assertEqual(labels(record, response(refusal=refusal, booking=booking, consultation_offset_days=1))[:3],
                         ("Appointment Scheduled", "Clinic Visit", "High"))

    def test_agent_words_are_not_a_customer_refusal(self):
        record = call("Agent: Remove my number, they always say.\nCustomer: Tell me more about the treatment.")
        refusal = {"kind": "Do Not Contact", "turn": 1, "quote": "Remove my number"}
        self.assertEqual(labels(record, response(refusal=refusal))[0], "Follow-up Required")

    def test_booking_needs_a_confirmation_grounded_in_the_transcript(self):
        self.assertEqual(labels(call(BOOKED), response())[:3], ("Follow-up Required", "Further Discussion", "Medium"))
        self.assertEqual(labels(call(BOOKED), response(booking=CONFIRMED, consultation_offset_days=1))[:3],
                         ("Appointment Scheduled", "Clinic Visit", "High"))
        self.assertEqual(labels(call(BOOKED), response(booking=CONFIRMED, consultation_offset_days=7))[2], "Medium")
        fabricated = {**CONFIRMED, "quote": "See you tomorrow at two"}
        self.assertEqual(labels(call(BOOKED), response(booking=fabricated))[0], "Follow-up Required")

    def test_no_meaningful_dialogue_is_unable_to_assess(self):
        self.assertEqual(labels(call("Agent: Hello? Hello?"), response(meaningful=False))[:3],
                         ("Unable to Assess", "Incomplete Conversation", "Not Assessable"))


class LeadQualityTests(TestCase):
    def test_workbook_order(self):
        signals = dict(need_established=True, exploratory_only=False, defers_beyond_30_days=False,
                       consultation_offset_days=1)
        cases = [("Invalid Lead", {}, "Not Qualified"), ("Not Interested", {}, "Low"),
                 ("Unable to Assess", {}, "Not Assessable"), ("Follow-up Required", {}, "Medium"),
                 ("Follow-up Required", {"need_established": False}, "Not Assessable"),
                 ("Follow-up Required", {"exploratory_only": True}, "Low"),
                 ("Follow-up Required", {"defers_beyond_30_days": True}, "Low"),
                 ("Appointment Scheduled", {}, "High"),
                 ("Appointment Scheduled", {"consultation_offset_days": 7}, "Medium")]
        for disposition, change, expected in cases:
            with self.subTest(disposition=disposition, change=change):
                self.assertEqual(derive_quality(disposition, {**signals, **change}), expected)
