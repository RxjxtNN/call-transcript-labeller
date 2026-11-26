from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from helpers import agreed, demo_call, option, response
from labeler.data import read_jsonl
from labeler.providers import ProviderError
from labeler.runner import predict, rescore

MODEL = "groq/openai/gpt-oss-120b"
KEY = {"GROQ_API_KEY": "test-key"}
# demo_call: the customer cannot yet afford the fee and asks for a call tomorrow at four; the agent agrees.
FIRST = response(blockers=["Cost Concern"], callback=agreed(
    1, "Call tomorrow at four?", 2, "Okay, I'll call tomorrow at four.", option("days", 1, "16:00", "tomorrow at four")))
FIRST["follow_up"]["reason_turn"] = 1
SECOND = {"final_reason": {"label": "Cost Concern", "turn": 1, "quote": "afford the fee"},
          "postponement": {"present": False, "turn": None, "quote": ""}, "callback": FIRST["callback"]}
EXPECTED = {"transcript_id": "demo-001", "disposition": "Follow-up Required", "sub_disposition": "Cost Concern",
            "lead_quality": "Medium", "next_call_at": "2026-11-10T16:00:00+05:30"}


def two_calls(root):
    source = root / "calls.jsonl"
    source.write_text(json.dumps(demo_call()) + "\n" + json.dumps(dict(demo_call(), transcript_id="next")) + "\n")
    return source


def run(root, source, **extra):
    return SimpleNamespace(**{"model": MODEL, "input": source, "out": root / "p.jsonl", "ids": None,
                              "resume": False, **extra})


class RunnerTests(TestCase):
    def test_both_passes_write_prediction_and_log_and_rescore_reproduces_it(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            args = run(root, two_calls(root))
            with patch.dict("os.environ", KEY), patch("labeler.passes.first_pass", return_value=(FIRST, Counter(prompt_tokens=5, completion_tokens=1))), \
                    patch("labeler.passes.second_pass", side_effect=[(SECOND, Counter(prompt_tokens=2, completion_tokens=1)),
                                                                     ProviderError("HTTP 400")]):
                predict(args)
            self.assertEqual(next(read_jsonl(args.out)), EXPECTED)
            log = list(read_jsonl(root / "p.jsonl.log.jsonl"))
            self.assertEqual((log[0]["prompt_tokens"], log[0]["second_pass"]["final_reason"]["label"]), (7, "Cost Concern"))
            self.assertEqual(log[1]["note"], "second pass failed: HTTP 400")  # Kept the first-pass prediction.
            rescore(root / "p.jsonl.log.jsonl", args.input, root / "again.jsonl")
            self.assertEqual(list(read_jsonl(root / "again.jsonl")), list(read_jsonl(args.out)))

    def test_failed_call_is_logged_the_run_continues_and_resume_retries_it(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            args = run(root, two_calls(root))
            usage = Counter(prompt_tokens=0, completion_tokens=0)
            with patch.dict("os.environ", KEY), patch("labeler.passes.first_pass", side_effect=[ProviderError("HTTP 429"), (FIRST, usage)]), \
                    patch("labeler.passes.second_pass", return_value=(SECOND, usage)):
                with self.assertRaisesRegex(ValueError, "1 of 2 calls failed"):
                    predict(args)
            self.assertEqual([row["transcript_id"] for row in read_jsonl(args.out)], ["next"])
            args.resume = True
            with patch.dict("os.environ", KEY), patch("labeler.passes.first_pass", return_value=(FIRST, usage)) as again, \
                    patch("labeler.passes.second_pass", return_value=(SECOND, usage)):
                predict(args)
                self.assertEqual([c.args[0]["transcript_id"] for c in again.call_args_list], ["demo-001"])
                args.model = "groq/openai/gpt-oss-20b"
                with self.assertRaisesRegex(ValueError, "resume requires the same"):
                    predict(args)

    def test_ids_select_a_subset(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ids.txt").write_text("next\n")
            args = run(root, two_calls(root), ids=root / "ids.txt")
            usage = Counter(prompt_tokens=0, completion_tokens=0)
            with patch.dict("os.environ", KEY), patch("labeler.passes.first_pass", return_value=(FIRST, usage)), \
                    patch("labeler.passes.second_pass", return_value=(SECOND, usage)):
                predict(args)
            self.assertEqual([row["transcript_id"] for row in read_jsonl(args.out)], ["next"])

    def test_missing_api_key_fails_before_any_call(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True), \
                patch("labeler.runner.load_env"):
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "GROQ_API_KEY"):
                predict(run(root, two_calls(root)))
