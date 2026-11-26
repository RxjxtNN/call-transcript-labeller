"""JSONL input and output, the workbook CSV import, and the assignment's scoring contract."""

from collections import Counter
import csv
import json

from .callbacks import call_time

INPUT_FIELDS = ("transcript_id", "call_started_at", "timezone", "transcript")
WEIGHTS = {"disposition": 15, "sub_disposition": 20, "lead_quality": 15, "next_call_at": 20}
OUTPUT_FIELDS = {"transcript_id", *WEIGHTS}


def read_jsonl(path, invalid_lines=None):
    """Yield objects with a string transcript_id; collect bad line numbers instead of failing if asked."""
    with path.open(encoding="utf-8") as file:
        for number, line in enumerate(file, 1):
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get("transcript_id"), str):
                    raise ValueError("expected an object with a string transcript_id")
                yield row
            except ValueError as error:
                if invalid_lines is None:
                    raise ValueError(f"{path}:{number}: {error}") from error
                invalid_lines.append(number)


def read_ids(path):
    """Transcript IDs from a file with one per line, or None when no file is given."""
    return set(path.read_text().split()) if path else None


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def validated_calls(rows):
    """Only the four input fields, with unique IDs, Asia/Kolkata, and a parseable timestamp."""
    calls, ids = [], set()
    for row in rows:
        call = {key: row[key] for key in INPUT_FIELDS}
        call_id = call["transcript_id"]
        if not call_id or call_id in ids:
            raise ValueError(f"blank or duplicate call ID: {call_id!r}")
        if call["timezone"] != "Asia/Kolkata" or not isinstance(call["transcript"], str):
            raise ValueError(f"{call_id}: expected Asia/Kolkata and a transcript string")
        call_time(call["call_started_at"])
        ids.add(call_id)
        calls.append(call)
    if not calls:
        raise ValueError("no input calls")
    return calls


def import_calls(source, destination):
    """Workbook CSV export -> input.jsonl (inputs only) and gold.jsonl (labels, 'null' -> JSON null)."""
    with source.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    calls = validated_calls(rows)
    gold = [{"transcript_id": row["transcript_id"],
             **{key: None if key == "next_call_at" and row[key] == "null" else row[key] for key in WEIGHTS}}
            for row in rows]
    write_jsonl(destination / "input.jsonl", calls)
    write_jsonl(destination / "gold.jsonl", gold)
    print(f"Imported {len(calls)} calls into {destination}")


def score(gold, predictions, ids=None):
    """Per-field accuracy, weighted score out of 70, and exact match; missing or duplicate IDs score 0."""
    gold = list(gold)
    answers = {row["transcript_id"]: row for row in gold}
    if len(answers) != len(gold):
        raise ValueError("duplicate reference ID")
    counts = Counter(row["transcript_id"] for row in predictions)
    guesses = {row["transcript_id"]: row for row in predictions}
    selected = set(answers) if ids is None else ids
    if not selected or selected - answers.keys():
        raise ValueError("empty score set or unknown reference IDs")
    hits, exact, errors = Counter(), 0, []
    for call_id in sorted(selected):
        expected, actual = answers[call_id], guesses.get(call_id, {})
        once = counts[call_id] == 1
        fields = {key: once and key in actual and actual[key] == expected[key] for key in WEIGHTS}
        fields["sub_disposition"] &= fields["disposition"]  # Credit only with the correct parent.
        hits.update(key for key, correct in fields.items() if correct)
        exact += all(fields.values()) and actual.keys() == OUTPUT_FIELDS
        errors += [{"transcript_id": call_id, "field": key, "expected": expected[key], "actual": actual.get(key)}
                   for key, correct in fields.items() if not correct]
    size = len(selected)
    return {
        "records": size, "accuracy": {key: hits[key] / size for key in WEIGHTS},
        "weighted_score_out_of_70": round(sum(hits[key] * weight for key, weight in WEIGHTS.items()) / size, 2),
        "exact_match": exact / size, "missing_ids": sorted(selected - guesses.keys()),
        "duplicate_ids": sorted(key for key in selected if counts[key] > 1),
        "extra_ids": sorted(guesses.keys() - answers.keys()), "errors": errors,
    }
