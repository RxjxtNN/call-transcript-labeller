# Anthropod call transcript assignment

The labeler gives each clinic call a disposition, sub-disposition, lead quality, and next call time (policy assignment-v2). It follows the workbook's recommended design. A model answers small questions, each with the turn and verbatim quote that support it. Python applies the Label Rules sheet (D1–D6, SUB, LQ, F1–F12) to the grounded answers.

## Run

The assignment workbook and dataset are kept locally. The repository includes a synthetic sample at `examples/demo_call.jsonl`.

Python 3.10 or later, standard library only. Put `GROQ_API_KEY` (and `GEMINI_API_KEY` for testing) in the environment or in a `.env` file.

```bash
python label_calls.py predict data/input.jsonl --out outputs/predictions.jsonl
python label_calls.py score data/gold.jsonl outputs/predictions.jsonl
```

`predict` writes one JSON object per call with exactly the five output keys.

| Option | Effect |
|---|---|
| `--model` | Default `groq/openai/gpt-oss-20b`. Use `gemini/gemini-3.5-flash-lite` for testing. |
| `--ids FILE` | Label only the listed transcript IDs. |
| `--resume` | Retry only the calls missing from `--out`, after checking that the input, IDs, prompts, model, and settings are unchanged. |

Each run writes two files next to the predictions:
- `<out>.log.jsonl`: every call's status, rule notes, token counts, and both passes' answers. API errors are logged as sanitized reasons only.
- `<out>.run.json`: the run settings.

Other commands:

```bash
python label_calls.py import data/labeled_calls.csv   # workbook CSV -> data/input.jsonl + data/gold.jsonl
python label_calls.py rescore outputs/predictions.jsonl.log.jsonl data/input.jsonl --out outputs/rescored.jsonl
python -m unittest discover -s tests                     # offline tests
python detect_caller_gender.py data/input.jsonl --out outputs/caller_gender.jsonl
```

`rescore` re-applies the current Python rules to a run's saved model answers without calling a model, so a rule change can be checked for free.

**Demo UI (optional).** A plain Streamlit page in `frontend_streamlitapp/` labels one pasted transcript with the same pipeline and shows the tags, the rules applied, and the quotes the model cited. It is the only part that needs a third-party package.

```bash
pip install -r frontend_streamlitapp/requirements.txt
streamlit run frontend_streamlitapp/app.py
```

**Testing workflow.** Test changes with Gemini on a fixed random 15-call subset:

```bash
python label_calls.py predict data/input.jsonl --model gemini/gemini-3.5-flash-lite --ids data/eval15_ids.txt --out outputs/eval15.jsonl
python label_calls.py score data/gold.jsonl outputs/eval15.jsonl --ids data/eval15_ids.txt
```

Groq runs once on all 50 calls for the submission.

## How a call is labeled

1. **Turns.** [labeler/transcript.py](labeler/transcript.py) numbers each transcript line with its speaker. It also flags `callback_candidates`: a timed contact proposal ("in 15 minutes", "next week", a weekday or clock time) answered by the other speaker within two turns.
2. **First pass.** [prompts/first_pass.md](prompts/first_pass.md) sends the full transcript. The model answers:
   - the outcome questions: invalid-lead reason, final refusal, confirmed booking, meaningful enquiry;
   - the follow-up blocker;
   - the callback;
   - four lead signals.
3. **Disposition.** [labeler/decisions.py](labeler/decisions.py) applies D6: Invalid Lead > Not Interested > Appointment Scheduled > Follow-up Required > Unable to Assess.
   - An answer counts only if its quote is found in the cited turn.
   - A refusal must come from the customer, and a later booking supersedes it.
4. **Second pass, Follow-up calls only.** [prompts/follow_up.md](prompts/follow_up.md) sends the closing 30 turns plus every turn the first pass cited. It asks for the final reason, a separate postponement answer, and the callback, and includes four short examples from development calls.
   - The final reason must cite a caller turn.
   - If this request fails, the call keeps its first-pass answer.
5. **Callback time.** [labeler/callbacks.py](labeler/callbacks.py) applies F1–F12.
   - An agreed time needs a quoted proposal and the other speaker's direct reply.
   - Otherwise a vague postponement gives +3 days at 11:00, and an ordinary follow-up gives +1 day at 11:00.
   - Invalid Lead, Not Interested and Unable to Assess get null.
6. **Lead quality.** It is derived from the lead signals in the LQ order: Not Qualified, Not Assessable, Low, High, Medium.

## Settings

| Provider | Settings |
|---|---|
| Groq | Temperature 0, `reasoning_effort=low`, 4,096 output tokens, 45-second timeout. |
| Gemini | Temperature 0, 2,048 output tokens, 30-second timeout. Requests start at least 5 seconds apart. |

Retries:
- **HTTP 429 and 5xx:** retried after the provider's stated wait or a backoff (Groq up to 5 times, Gemini once). Daily-limit 429s fail fast.
- **HTTP 413:** retried once with a smaller output cap.
- **No model fallback** is ever applied.

Groq free-tier limits:
- **Speed:** the limit is 8,000 tokens per minute, which allows roughly one call per minute.
- **Daily cap:** the 50 calls need about 370k tokens, against roughly 200k per model per day.

## Layout

| Path | Purpose |
|---|---|
| `label_calls.py` | Command line |
| `labeler/` | `labels`, `transcript`, `schemas`, `passes`, `decisions`, `callbacks`, `finalize`, `providers`, `runner`, `data` |
| `prompts/` | First-pass and Follow-up prompts |
| `detect_caller_gender.py` | Caller gender cues without a model |
| `tests/` | One offline test file per module |
| `examples/demo_call.jsonl` | Synthetic call for a quick live check |
| `frontend_streamlitapp/` | Optional Streamlit demo that reuses the labeler |
| `data/`, `outputs/` | Local data and runs (Git-ignored); old runs are in `outputs/archive/` |

## Caller gender (separate task)

[detect_caller_gender.py](detect_caller_gender.py) uses no model.
- **Evidence order:** the caller's own self-identification wins. Otherwise it uses direct address by the agent ("Yes, sir.", "Can you hear me, madam?", "Hi, Ms. Rao?").
- **Unknown:** conflicting titles, quoted text, and phone handoffs give `unknown`.
- **Result:** it finds a cue in 48 of 50 calls.
- **Limits:** these are transcript cues, not verified gender, because the workbook has no gender labels. Earlier versions V1 (36/50) and V2 (44/50) are described in the project history.
