"""Batch runner: label calls, write predictions as they arrive, log each call's evidence, resume, and rescore."""

from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import monotonic, sleep

from . import passes
from .data import read_ids, read_jsonl, validated_calls, write_jsonl
from .finalize import apply_rules, finalize_prediction, merge_follow_up
from .providers import ProviderError, api_key, model_settings
from .transcript import dialogue_turns

ROOT = Path(__file__).resolve().parent.parent
GEMINI_SPACING = 5  # Seconds between Gemini requests (free-tier pacing).
_last_request = None


def load_env():
    """KEY=value lines from .env; variables already set in the shell win."""
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.lstrip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def load_prompts():
    """Both system prompts, used by the CLI runner and the Streamlit demo."""
    return {name: (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8") for name in ("first_pass", "follow_up")}


def paced(model):
    """Space Gemini requests a few seconds apart; Groq rate limits are handled by retries."""
    global _last_request
    if _last_request is not None and model.startswith("gemini/"):
        sleep(max(0, GEMINI_SPACING - (monotonic() - _last_request)))
    _last_request = monotonic()


def sanitized(error):
    """Provider errors are already sanitized; other exceptions may contain transcript text."""
    return str(error) if isinstance(error, ProviderError) else type(error).__name__


def label_call(call, model, prompts, settings):
    """First pass for every call; a second pass for Follow-up calls. -> (prediction, log row)."""
    turns = dialogue_turns(call["transcript"])
    by_id = {turn["id"]: turn for turn in turns}
    paced(model)
    first, usage = passes.first_pass(call, turns, model, prompts["first_pass"], settings)
    prediction, rule = finalize_prediction(call, first, by_id)
    row = {"status": "returned", "first_pass": first, "second_pass": None}
    if prediction["disposition"] == "Follow-up Required":
        paced(model)
        try:
            second, more = passes.second_pass(call, turns, model, prompts["follow_up"], first, settings)
            prediction, rule = finalize_prediction(call, merge_follow_up(call, first, second, by_id), by_id)
            row["second_pass"] = second
            usage.update(more)  # update(), not +: a Counter sum drops zero counts.
        except Exception as error:  # Keep the first-pass prediction rather than losing the call.
            row["note"] = "second pass failed: " + sanitized(error)
    return prediction, {**row, "rule": rule, **usage}


def predict(args):
    out = args.out
    manifest, log_path = out.with_name(out.name + ".run.json"), out.with_name(out.name + ".log.jsonl")
    if args.input.resolve() in {out.resolve(), manifest.resolve(), log_path.resolve()}:
        raise ValueError("outputs must not overwrite the input")
    load_env()
    api_key(args.model)  # Fail before any call if the model or its key is wrong.
    ids = read_ids(args.ids)
    calls = [call for call in validated_calls(read_jsonl(args.input)) if ids is None or call["transcript_id"] in ids]
    prompts, settings = load_prompts(), model_settings(args.model)
    run = {"model": args.model, "settings": settings, "ids": sorted(ids) if ids else None,
           "input_sha256": sha256(args.input.read_bytes()).hexdigest(),
           "prompts_sha256": sha256("".join(prompts.values()).encode()).hexdigest()}
    completed = set()
    if args.resume:
        if not manifest.exists() or json.loads(manifest.read_text()) != run:
            raise ValueError("resume requires the same input, IDs, prompts, model, and settings")
        completed = {row["transcript_id"] for row in read_jsonl(out)}
    else:
        manifest.write_text(json.dumps(run) + "\n", encoding="utf-8")
    usage, failures, start, mode = Counter(), Counter(), monotonic(), "a" if args.resume else "w"
    with out.open(mode, encoding="utf-8") as output, log_path.open(mode, encoding="utf-8") as log:
        for call in calls:
            if call["transcript_id"] in completed:
                continue
            try:
                prediction, row = label_call(call, args.model, prompts, settings)
            except Exception as error:
                failures[sanitized(error)] += 1
                write_line(log, {"transcript_id": call["transcript_id"], "status": "error", "reason": sanitized(error)})
                print(f"{call['transcript_id']}: prediction failed ({sanitized(error)})", file=sys.stderr)
                continue
            write_line(output, prediction)
            write_line(log, {"transcript_id": call["transcript_id"], **row})
            completed.add(call["transcript_id"])
            usage.update({name: row.get(name, 0) for name in ("prompt_tokens", "completion_tokens")})
    print(json.dumps({"model": args.model, "records": len(completed), "failed": failures.total(),
                      "seconds": round(monotonic() - start, 1), **usage}), file=sys.stderr)
    if failures:
        raise ValueError(f"{failures.total()} of {len(calls)} calls failed ({dict(failures)}). "
                         f"{len(completed)} saved. Run again with --resume to retry only the failed calls.")


def rescore(log_path, input_path, out):
    """Re-apply the current Python rules to a run's saved model answers, without calling a model."""
    calls = {call["transcript_id"]: call for call in read_jsonl(input_path)}
    rows = [row for row in read_jsonl(log_path) if row["status"] == "returned"]
    write_jsonl(out, [apply_rules(calls[row["transcript_id"]], row["first_pass"], row["second_pass"])[0] for row in rows])
    print(f"Rescored {len(rows)} calls into {out}", file=sys.stderr)


def write_line(file, row):
    file.write(json.dumps(row, ensure_ascii=False) + "\n")
    file.flush()
