# Evaluation results

These measurements use the labeled development calls supplied with the assignment. Some of these calls informed prompts and rule changes. The separate evaluation set was unavailable, so the table reports development-set performance.

| Model and run | Scored calls | Exact match | Weighted score / 70 | Disposition | Sub-disposition | Lead quality | Callback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemini 3.5 Flash-Lite, full development set | 50 | 40/50 (80%) | 64.10 | 48/50 | 42/50 | 47/50 | 47/50 |
| Groq GPT-OSS 20B, live baseline | 20 | 11/20 (55%) | 61.25 | 20/20 | 17/20 | 19/20 | 15/20 |
| Groq GPT-OSS 20B, same outputs rescored after a local callback fix | 20 | 13/20 (65%) | 62.25 | 20/20 | 16/20 | 19/20 | 17/20 |

Exact match requires all four fields to match for a call. The weighted score uses the assignment's field weights. The Groq live run attempted 21 calls and returned 20 predictions. Counting the failed request as a miss gives 11/21 exact matches for the live baseline. The rescore reused saved model responses and reflects a local code revision. A full 50-call Groq score was unavailable.

## Non-transformer caller-gender evaluation

The classifier returned a cue for 48 of 50 calls (96% coverage) and abstained on two. A manual review confirmed that all 48 selected cues were direct forms of address to the caller. The dataset provides no verified gender labels, so caller-gender accuracy could not be measured.
