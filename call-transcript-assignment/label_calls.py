"""Command line: import the workbook CSV, predict labels, rescore saved answers, or score predictions."""

import argparse
import json
from pathlib import Path

from labeler.data import import_calls, read_ids, read_jsonl, score
from labeler.providers import DEFAULT_MODEL
from labeler.runner import ROOT, predict, rescore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="workbook CSV -> data/input.jsonl and data/gold.jsonl")
    importer.add_argument("source", type=Path)
    importer.add_argument("--data-dir", type=Path, default=ROOT / "data")
    prediction = commands.add_parser("predict", help="input JSONL -> predictions JSONL (+ .log.jsonl, .run.json)")
    prediction.add_argument("input", type=Path)
    prediction.add_argument("--out", type=Path, required=True)
    prediction.add_argument("--model", default=DEFAULT_MODEL, help=f"provider/model (default {DEFAULT_MODEL})")
    prediction.add_argument("--ids", type=Path, help="label only these transcript IDs (one per line)")
    prediction.add_argument("--resume", action="store_true", help="retry only calls missing from --out")
    rescoring = commands.add_parser("rescore", help="re-apply the Python rules to a run's saved model answers")
    rescoring.add_argument("log", type=Path, help="the run's <predictions>.log.jsonl")
    rescoring.add_argument("input", type=Path)
    rescoring.add_argument("--out", type=Path, required=True)
    scoring = commands.add_parser("score", help="field accuracy, weighted /70, and exact match")
    scoring.add_argument("gold", type=Path)
    scoring.add_argument("predictions", type=Path)
    scoring.add_argument("--ids", type=Path, help="score only these IDs (one per line)")
    args = parser.parse_args()
    try:
        if args.command == "import":
            import_calls(args.source, args.data_dir)
        elif args.command == "predict":
            predict(args)
        elif args.command == "rescore":
            rescore(args.log, args.input, args.out)
        else:
            invalid_lines = []
            report = score(read_jsonl(args.gold), list(read_jsonl(args.predictions, invalid_lines)), read_ids(args.ids))
            print(json.dumps({**report, "invalid_prediction_lines": invalid_lines}, ensure_ascii=False, indent=2))
    except (KeyError, ValueError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
