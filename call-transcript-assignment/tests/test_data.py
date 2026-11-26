import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from labeler.data import import_calls, read_jsonl, score


class DataTests(TestCase):
    def test_import_keeps_multiline_text_and_separates_gold(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "calls.csv"
            row = ["id", "2026-11-09T14:00:00+05:30", "Asia/Kolkata", "Agent: Hello\nCustomer: Hi",
                   "Unable to Assess", "Incomplete Conversation", "Not Assessable", "null"]
            with source.open("w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(("transcript_id", "call_started_at", "timezone", "transcript",
                                 "disposition", "sub_disposition", "lead_quality", "next_call_at"))
                writer.writerow(row)
            import_calls(source, root)
            call = next(read_jsonl(root / "input.jsonl"))
            self.assertEqual(call["transcript"], row[3])
            self.assertNotIn("lead_quality", call)  # Gold labels never reach the input file.
            self.assertIsNone(next(read_jsonl(root / "gold.jsonl"))["next_call_at"])

    def test_scoring_contract(self):
        gold = dict(transcript_id="a", disposition="Appointment Scheduled", sub_disposition="Clinic Visit",
                    lead_quality="High", next_call_at=None)
        wrong_parent = dict(gold, disposition="Follow-up Required")
        wrong_parent.pop("next_call_at")
        report = score([gold], [wrong_parent])
        self.assertEqual((report["weighted_score_out_of_70"], report["exact_match"]), (15, 0))  # lead quality only
        self.assertEqual(score([gold], [gold, gold])["duplicate_ids"], ["a"])
        self.assertEqual(score([gold], [gold])["weighted_score_out_of_70"], 70)
        self.assertEqual(score([gold], [])["missing_ids"], ["a"])
