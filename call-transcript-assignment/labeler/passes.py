"""The two model requests: what each pass sends and the evidence it must return."""

import json

from .providers import send_model
from .schemas import FIRST_PASS, FOLLOW_UP
from .transcript import callback_candidates, format_turns

TAIL_TURNS = 30  # The second pass reads the call's closing turns plus every turn of interest.


def ask(call, turns, model, prompt, schema, settings, keep=None):
    """Send the call (all turns, or only those in keep) and check every required field came back."""
    pairs = callback_candidates(turns)
    if keep is not None:
        keep = (keep | {turn_id for pair in pairs for turn_id in pair}) - {None}
    message = json.dumps({"call_started_at": call["call_started_at"], "timezone": call["timezone"],
                          "callback_candidates": ", ".join(f"{a}->{b}" for a, b in pairs) or "none found",
                          "turns": format_turns(turns, keep)}, ensure_ascii=False)
    answer, usage = send_model(model, prompt, message, schema, settings)
    if missing := set(schema["json_schema"]["schema"]["required"]) - answer.keys():
        raise ValueError(f"response is missing {sorted(missing)}")
    return answer, usage


def first_pass(call, turns, model, prompt, settings):
    """Full transcript -> outcome answers, follow-up reason, callback, lead signals."""
    return ask(call, turns, model, prompt, FIRST_PASS, settings)


def second_pass(call, turns, model, prompt, first, settings):
    """Follow-up calls: closing turns plus the first pass's cited turns -> final reason, postponement, callback."""
    callback = first["callback"]
    keep = {turn["id"] for turn in turns[-TAIL_TURNS:]} | {
        first["follow_up"]["reason_turn"], callback["deferral_turn"],
        *((callback["agreement"] or {}).get(key) for key in ("proposal_turn", "acknowledgment_turn"))}
    return ask(call, turns, model, prompt, FOLLOW_UP, settings, keep)
