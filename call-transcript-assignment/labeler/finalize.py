"""Combine one call's grounded model answers into the five output fields."""

from .callbacks import call_time, callback_time, grounded_callback
from .decisions import choose_disposition, derive_quality, follow_up_child
from .labels import PRIMARY_BLOCKERS
from .transcript import grounded_turn, turns_by_id

NO_REASON = {"primary_blockers": [], "review_information": False, "reason_turn": None}


def finalize_prediction(call, response, by_id=None):
    """Return the prediction row and a short note of the rules that produced it."""
    by_id = by_id or turns_by_id(call)
    disposition, child, note = choose_disposition(by_id, response["outcome"])
    callback, discarded = response["callback"], False
    if disposition in ("Appointment Scheduled", "Follow-up Required"):
        callback, discarded = grounded_callback(by_id, callback)
    target, rule, agreed = callback_time(call_time(call["call_started_at"]), disposition, callback)
    if disposition == "Follow-up Required":
        child = follow_up_child(response["follow_up"], agreed, callback["vague_postponement"])
    prediction = {
        "transcript_id": call["transcript_id"], "disposition": disposition, "sub_disposition": child,
        "lead_quality": derive_quality(disposition, response["lead_signals"]),
        "next_call_at": target.isoformat(timespec="seconds") if target else None,
    }
    return prediction, f"{note}; {rule}" + (" (discarded unsupported callback options)" if discarded else "")


def merge_follow_up(call, first, second, by_id=None):
    """The first pass's answers with the second pass's reason and callback; claims count only when grounded."""
    by_id = by_id or turns_by_id(call)
    reason, postponed = second["final_reason"], second["postponement"]
    # The focused pass's callback wins when it found a timed one; otherwise keep the first pass's, which
    # grounded_callback still has to verify (quoted proposal, the other speaker's direct reply).
    callback = second["callback"] if second["callback"]["options"] else \
        {**first["callback"], "vague_postponement": second["callback"]["vague_postponement"],
         "deferral_turn": second["callback"]["deferral_turn"]}
    # F7: a grounded postponement sets the +3 day fallback whichever blocker owns the label. It may be the agent
    # restating the caller's deferral ("you can let me know"), so any speaker counts.
    deferral = postponed["present"] and grounded_turn(by_id, postponed["turn"], postponed["quote"])
    if deferral:
        callback = {**callback, "vague_postponement": True, "deferral_turn": deferral["id"]}
    if not grounded_turn(by_id, reason["turn"], reason["quote"], "agent"):  # The caller's reason, not the agent's.
        # No citable final reason: keep the first pass's blocker only if it cites a real turn.
        follow_up = first["follow_up"] if first["follow_up"]["reason_turn"] in by_id else NO_REASON
        return {**first, "follow_up": follow_up, "callback": callback}
    if reason["label"] == "Vague Deferral" and not deferral:  # The final reason is itself the postponement.
        callback = {**callback, "vague_postponement": True, "deferral_turn": reason["turn"]}
    follow_up = {"primary_blockers": [reason["label"]] if reason["label"] in PRIMARY_BLOCKERS else [],
                 "review_information": reason["label"] == "Information Requested", "reason_turn": reason["turn"]}
    return {**first, "follow_up": follow_up, "callback": callback}


def apply_rules(call, first, second=None, by_id=None):
    """Prediction from saved answers: the second pass applies only when the call is Follow-up Required."""
    by_id = by_id or turns_by_id(call)
    prediction, rule = finalize_prediction(call, first, by_id)
    if second and prediction["disposition"] == "Follow-up Required":
        return finalize_prediction(call, merge_follow_up(call, first, second, by_id), by_id)
    return prediction, rule
