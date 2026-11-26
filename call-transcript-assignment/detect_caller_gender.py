"""Find attributable caller-gender cues using only the transcript and local rules (no model).

Evidence, in priority order: the caller's own self-identification ("I am a woman"), then the agent addressing
the caller directly ("Yes, sir.", "Can you hear me, madam?", "Hi, Ms. Rao?"). Conflicting cues give "unknown".
These are transcript cues, not verified gender: the workbook has no gender labels.
"""

import argparse
from collections import Counter
from pathlib import Path
import re

from labeler.data import read_jsonl, write_jsonl
from labeler.transcript import dialogue_turns

GENDER = {"woman": "female", "female": "female", "man": "male", "male": "male",
          "non-binary": "nonbinary", "non binary": "nonbinary",
          "sir": "male", "ma'am": "female", "madam": "female",
          "mr": "male", "mrs": "female", "ms": "female", "miss": "female"}
# Self-identification at the start of a sentence; not possessive ("a man's caregiver") and not a question.
SELF = re.compile(r"(?:^|[.!?]\s+)(?:yes[, ]+)?(?:i am|i'm)\s+(?:an?\s+)?"
                  r"(woman|man|female|male|non[- ]binary)\b(?!'s\b)(?![^.!?]*\?)", re.I)
# A title must stand alone at the start or end of a clause, which rejects "Sir will call you".
VOCATIVE = re.compile(r"^(?:(?:yes|no|hello|okay|ok|thank you)[, ]+)?(?P<opening>sir|ma'am|madam)(?=[,.!?]|$)"
                      r"|,\s*(?P<closing>sir|ma'am|madam)(?=[,.!?]|$)", re.I)
GREETING = re.compile(r"(?:^|[.!?]\s+)(?:(?:hi|hello|alright|okay|ok|yes|no|thank you|by the way)[,\s]+)+"
                      r"(sir|ma'am|madam)(?=[,.!?]|$)", re.I)
NAMED = re.compile(r"(?:^|[.!?,]\s+|^(?i:so|hi|hello|yes)\s+)(?:(?i:see here)\s+)?(?i:(mr|mrs|ms|miss))\.?\s+"
                   r"[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,2}(?=[,?!])")
HANDOFF = re.compile(r"\b(?:pass|hand|give)\s+(?:the|my|this)\s+phone\s+to\b"
                     r"|\bput\s+(?:my|your|the)\s+\w+\s+on\s+(?:the\s+)?(?:phone|line)\b", re.I)
QUOTED = re.compile(r'“[^”]*”|"[^"]*"')


def detect(transcript):
    """-> (caller_gender, evidence excerpt, evidence source, agent title counts)."""
    turns = [(turn["speaker"], turn["text"].strip().replace("’", "'")) for turn in dialogue_turns(transcript)]
    caller_present = any(role != "agent" for role, _ in turns)
    explicit, addresses, counts = {}, {}, Counter()
    for role, text in turns:
        if HANDOFF.search(text):
            break  # Later cues may describe someone else on the line.
        if role != "agent":
            for cue in SELF.findall(text):
                explicit.setdefault(GENDER[cue.lower()], text)
        elif caller_present:
            unquoted = QUOTED.sub("", text)
            titles = {(m["opening"] or m["closing"]).lower() for m in VOCATIVE.finditer(unquoted)}
            titles |= {m[1].lower() for m in GREETING.finditer(unquoted)} | {m[1].lower() for m in NAMED.finditer(unquoted)}
            counts.update(titles)
            for title in sorted(titles):
                addresses.setdefault(GENDER[title], text)
    evidence = explicit or addresses
    if len(evidence) != 1:
        return "unknown", None, None, dict(sorted(counts.items()))
    label, excerpt = next(iter(evidence.items()))
    return label, excerpt, "self_identification" if explicit else "agent_address", dict(sorted(counts.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for row in read_jsonl(args.input):
        gender, evidence, source, counts = detect(row["transcript"])
        rows.append({"transcript_id": row["transcript_id"], "caller_gender": gender, "evidence": evidence,
                     "evidence_source": source, "agent_cue_counts": counts})
    write_jsonl(args.out, rows)
    print(f"{sum(row['caller_gender'] != 'unknown' for row in rows)}/{len(rows)} calls had an attributable cue.")


if __name__ == "__main__":
    main()
