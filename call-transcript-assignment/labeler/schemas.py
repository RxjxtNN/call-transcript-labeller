"""JSON schemas for the two model passes. Every field is required, so the shape is always the same."""

from .labels import FINAL_REASONS, INVALID_REASONS, LABELS, PRIMARY_BLOCKERS, REFUSALS

STRING = {"type": "string"}
INTEGER = {"type": "integer"}
BOOLEAN = {"type": "boolean"}
OPTIONAL_TURN = {"type": ["integer", "null"]}
CALLBACK_KINDS = ["days", "weekday", "this_weekday", "next_weekday", "next_week",
                  "date", "month_day", "months", "next_month", "minutes", "clock"]


def obj(**properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def cited(**extra):
    """An answer with the turn and verbatim quote that support it."""
    return obj(**extra, turn=OPTIONAL_TURN, quote=STRING)


CALLBACK = obj(
    agreement={"anyOf": [{"type": "null"}, obj(
        event={"type": "string", "enum": ["callback"]}, proposal_turn=INTEGER, acknowledgment_turn=INTEGER,
        proposal=STRING, acknowledgment=STRING)]},
    options={"type": "array", "items": obj(
        kind={"type": "string", "enum": CALLBACK_KINDS},
        value={"anyOf": [INTEGER, STRING, {"type": "null"}]},
        clock={"type": ["string", "null"]}, timing_phrase=STRING)},
    vague_postponement=BOOLEAN, deferral_turn=OPTIONAL_TURN,
)


def wrap(name, schema):
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


FIRST_PASS = wrap("call_evidence", obj(
    outcome=obj(
        invalid=cited(reason={"type": "string", "enum": ["none", *INVALID_REASONS]}),
        refusal=cited(kind={"type": "string", "enum": ["none", *REFUSALS]}),
        booking=cited(confirmed=BOOLEAN,
                      child={"type": ["string", "null"], "enum": [None, *LABELS["Appointment Scheduled"]]}),
        meaningful_enquiry=BOOLEAN,
    ),
    follow_up=obj(primary_blockers={"type": "array", "items": {"type": "string", "enum": list(PRIMARY_BLOCKERS)}},
                  review_information=BOOLEAN, reason_turn=OPTIONAL_TURN),
    callback=CALLBACK,
    lead_signals=obj(need_established=BOOLEAN, exploratory_only=BOOLEAN, defers_beyond_30_days=BOOLEAN,
                     consultation_offset_days=OPTIONAL_TURN),
    # Unused by Python but kept: removing it together with the prompt edits dropped the subset from 13/15 to
    # 11/15 (v9). It stays last because GPT-OSS closed the object early when this list came first.
    evidence={"type": "array", "items": STRING},
))

FOLLOW_UP = wrap("follow_up_reason", obj(
    final_reason=cited(label={"type": "string", "enum": list(FINAL_REASONS)}),
    postponement=cited(present=BOOLEAN),
    callback=CALLBACK,
))
