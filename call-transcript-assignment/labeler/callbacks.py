"""Callback evidence -> next_call_at, following rules F1–F12."""

from calendar import monthrange
from datetime import date, datetime, time, timedelta
import re

from .labels import IST, ORDINARY_CALLBACK_DAYS, VAGUE_CALLBACK_DAYS
from .transcript import normalized, quoted_in, words

DAYPARTS = {"morning": "10:00", "afternoon": "15:00", "evening": "18:00", "lunch": "13:00"}  # F5
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# A reply made only of these words asks for repetition; it does not acknowledge a proposal (F3).
CLARIFICATION = {"pardon", "sorry", "what", "hello", "huh", "hmm", "excuse", "me", "come", "again", "sir", "ma'am"}


def call_time(value):
    """call_started_at as an Asia/Kolkata datetime (F1)."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("call_started_at must include an offset")
    return parsed.astimezone(IST)


def after_months(today, months, first_day=False):
    """F11: same day number N months later, clamped to the month's end; or the first of next month."""
    year, month = divmod(today.year * 12 + today.month - 1 + months, 12)
    day = 1 if first_day else min(today.day, monthrange(year, month + 1)[1])
    return date(year, month + 1, day)


def resolve_option(start, option):
    """One accepted timing option -> datetime, or None when it is explicitly past (F6)."""
    kind, value = option["kind"], option["value"]
    clock = time.fromisoformat(option["clock"] or "11:00")  # F5: agreed day without a time = 11:00
    today = start.date()
    next_monday = today + timedelta(days=7 - today.weekday())
    if "weekday" in kind and value not in range(7):
        raise ValueError("weekday must be 0 (Monday) to 6 (Sunday)")
    if kind == "minutes":  # F10: from call_started_at, seconds preserved
        return start + timedelta(minutes=value) if value > 0 else None
    if kind == "date":
        day = date.fromisoformat(value)
    elif kind == "month_day":  # F6: next future occurrence (Feb 29 may need a leap year)
        month, number = map(int, value.split("-"))
        day = next(date(year, month, number) for year in range(today.year, today.year + 8)
                   if month != 2 or number != 29 or year % 4 == 0
                   if datetime.combine(date(year, month, number), clock, IST) > start)
    elif kind == "days":  # F4
        day = today + timedelta(days=value)
    elif kind in ("weekday", "this_weekday"):  # F4: nearest future occurrence
        offset = (value - today.weekday()) % 7
        if offset == 0 and (kind == "weekday" or clock <= start.time()):
            offset = 7
        day = today + timedelta(days=offset)
    elif kind == "next_weekday":  # F4: that day in the following Monday–Sunday week
        day = next_monday + timedelta(days=value)
    elif kind == "next_week":  # F4: next week alone = next Monday
        day = next_monday
    elif kind in ("months", "next_month"):  # F11
        day = after_months(today, 1 if kind == "next_month" else value, kind == "next_month")
    elif kind == "clock":  # F5: time only = today if still future, else tomorrow
        day = today + timedelta(days=clock <= start.time())
    else:
        raise ValueError(f"unsupported callback kind: {kind}")
    target = datetime.combine(day, clock, IST)
    return target if target > start else None


def normalize_timing(option, phrase):
    """Clear quoted phrases ('tomorrow evening', 'next Friday') override the model's encoding."""
    daypart = next((part for part in re.findall(r"[a-z]+", phrase) if part in DAYPARTS), None)
    days = re.fullmatch(r"(?:on )?(today|this|tomorrow)(?: morning| afternoon| evening| at lunch)?", phrase)
    weekday = re.fullmatch(r"(?:on )?(?:(next|this) )?(" + "|".join(WEEKDAYS) +
                           r")(?: morning| afternoon| evening| at lunch)?", phrase)
    if days and (days[1] != "this" or daypart):
        option = {**option, "kind": "days", "value": int(days[1] == "tomorrow")}
    elif weekday:
        kind = {"next": "next_weekday", "this": "this_weekday", None: "weekday"}[weekday[1]]
        option = {**option, "kind": kind, "value": WEEKDAYS.index(weekday[2])}
    elif phrase == "next week":
        option = {**option, "kind": "next_week", "value": None}
    if daypart and (days or weekday or phrase == daypart or not option["clock"]):
        option = {**option, "clock": DAYPARTS[daypart]}
    return option


def acknowledged(by_id, agreement):
    """F3: the proposal is quoted, and the other speaker's direct reply acknowledges it."""
    before, after = by_id.get(agreement["proposal_turn"]), by_id.get(agreement["acknowledgment_turn"])
    if not before or not after or {before["speaker"], after["speaker"]} != {"agent", "customer"}:
        return False
    replies = [turn["id"] for turn in sorted(by_id.values(), key=lambda turn: turn["id"])
               if turn["id"] > before["id"] and turn["speaker"] not in (before["speaker"], "unknown")]
    return (after["id"] in replies[:2]  # The answer to this proposal, not a later turn.
            and not set(words(after["text"])) <= CLARIFICATION
            and quoted_in(agreement["proposal"], before["text"])
            and quoted_in(agreement["acknowledgment"], after["text"]))


def grounded_callback(by_id, callback):
    """Keep timed options only when an acknowledged agreement quotes their timing phrase.

    Returns the cleaned callback and whether any option was discarded.
    """
    if callback["vague_postponement"] and callback["deferral_turn"] not in by_id:
        callback = {**callback, "vague_postponement": False}  # A postponement must cite a real turn.
    options, agreement = callback["options"], callback["agreement"]
    if not options:
        return callback, False
    if not agreement or not acknowledged(by_id, agreement):
        return {**callback, "options": []}, True
    quoted = [normalize_timing(option, phrase) for option in options
              if (phrase := normalized(option["timing_phrase"]))
              and (quoted_in(phrase, agreement["proposal"]) or quoted_in(phrase, agreement["acknowledgment"]))]
    return {**callback, "options": quoted}, len(quoted) != len(options)


def callback_time(start, disposition, callback):
    """F2 suppression, F3 earliest agreed future time, F7 vague +3 days, F8 ordinary +1 day.

    Returns (datetime or None, rule note, whether a specific callback was agreed).
    """
    if disposition not in ("Appointment Scheduled", "Follow-up Required"):
        return None, "F2: callback suppressed", False
    future = []
    for option in callback["options"]:
        try:
            if target := resolve_option(start, option):
                future.append(target)
        except (KeyError, TypeError, ValueError, StopIteration):
            pass  # A badly encoded option falls back like no option.
    if future:
        return min(future), "F3: acknowledged callback", True
    if disposition == "Appointment Scheduled":
        return None, "F8: booked consultation without a callback", False
    vague = callback["vague_postponement"]
    days = VAGUE_CALLBACK_DAYS if vague else ORDINARY_CALLBACK_DAYS
    rule = "F7: vague postponement" if vague else "F8: ordinary follow-up"
    return datetime.combine(start.date() + timedelta(days=days), time(11), IST), rule, False
