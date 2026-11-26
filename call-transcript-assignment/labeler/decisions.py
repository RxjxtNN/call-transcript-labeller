"""Workbook rules that turn grounded model answers into labels: D1–D6, SUB tie-breaking, and LQ."""

from .labels import INVALID_REASONS, LABELS, PRIMARY_BLOCKERS, REFUSALS
from .transcript import grounded_turn


def choose_disposition(by_id, outcome):
    """D6 precedence: Invalid Lead > Not Interested > Appointment Scheduled > Follow-up Required > Unable to Assess.

    Each answer counts only when its cited turn and quote are found in the transcript.
    Returns (disposition, child or None for Follow-up, note for the trace).
    """
    invalid = outcome["invalid"]
    if invalid["reason"] in INVALID_REASONS and grounded_turn(by_id, invalid["turn"], invalid["quote"]):
        return "Invalid Lead", invalid["reason"], "D1"
    booking = outcome["booking"]
    booked = booking["confirmed"] and grounded_turn(by_id, booking["turn"], booking["quote"])
    refusal = outcome["refusal"]
    refused = refusal["kind"] in REFUSALS and grounded_turn(by_id, refusal["turn"], refusal["quote"], "agent")
    if refused and not (booked and booking["turn"] > refusal["turn"]):  # D2: a later booking supersedes it.
        return "Not Interested", refusal["kind"], "D2"
    if booked:
        child = booking["child"] if booking["child"] in LABELS["Appointment Scheduled"] else "Clinic Visit"
        return "Appointment Scheduled", child, "D3"
    if outcome["meaningful_enquiry"]:
        return "Follow-up Required", None, "D4"
    return "Unable to Assess", "Incomplete Conversation", "D5"


def follow_up_child(follow_up, agreed_callback, vague):
    """SUB: a named blocker dominates; then Specific Callback, Information Requested, Vague Deferral, Further Discussion."""
    for label in PRIMARY_BLOCKERS:  # Tie-breaking order for equally primary blockers.
        if label in follow_up["primary_blockers"]:
            return label
    if agreed_callback:
        return "Specific Callback"
    if follow_up["review_information"]:
        return "Information Requested"
    return "Vague Deferral" if vague else "Further Discussion"


def derive_quality(disposition, signals):
    """LQ order: Not Qualified, Not Assessable, Low, High, then Medium."""
    fixed = {"Invalid Lead": "Not Qualified", "Unable to Assess": "Not Assessable", "Not Interested": "Low"}
    if disposition in fixed:
        return fixed[disposition]
    if not signals["need_established"]:
        return "Not Assessable"
    if signals["exploratory_only"]:
        return "Low"
    if disposition == "Appointment Scheduled":
        offset = signals["consultation_offset_days"]
        return "Medium" if type(offset) is int and offset >= 7 else "High"
    # Follow-up Required has no confirmed consultation, and LQ High needs one.
    return "Low" if signals["defers_beyond_30_days"] else "Medium"
