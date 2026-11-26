"""Shared builders for tests: a call record and a complete first-pass response with neutral defaults."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "2026-11-09T14:00:00+05:30"  # A Monday.


def call(transcript, call_id="t1", start=START):
    return {"transcript_id": call_id, "call_started_at": start, "timezone": "Asia/Kolkata", "transcript": transcript}


def no_callback(**overrides):
    return {"agreement": None, "options": [], "vague_postponement": False, "deferral_turn": None, **overrides}


def agreed(proposal_turn, proposal, acknowledgment_turn, acknowledgment, *options):
    return no_callback(agreement={"proposal_turn": proposal_turn, "proposal": proposal,
                                  "acknowledgment_turn": acknowledgment_turn, "acknowledgment": acknowledgment},
                       options=list(options))


def option(kind, value, clock, phrase):
    return {"kind": kind, "value": value, "clock": clock, "timing_phrase": phrase}


def response(invalid=None, refusal=None, booking=None, meaningful=True, blockers=(), review=False,
             callback=None, **signals):
    """A first-pass response for an open, meaningful enquiry unless overridden."""
    return {
        "outcome": {
            "invalid": invalid or {"reason": "none", "turn": None, "quote": ""},
            "refusal": refusal or {"kind": "none", "turn": None, "quote": ""},
            "booking": booking or {"confirmed": False, "child": None, "turn": None, "quote": ""},
            "meaningful_enquiry": meaningful,
        },
        "follow_up": {"primary_blockers": list(blockers), "review_information": review, "reason_turn": None},
        "callback": callback or no_callback(),
        "lead_signals": {"need_established": True, "exploratory_only": False, "defers_beyond_30_days": False,
                         "consultation_offset_days": None, **signals},
    }


def demo_call():
    return json.loads((ROOT / "examples/demo_call.jsonl").read_text().splitlines()[0])
