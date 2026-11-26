"""Demo UI: paste one transcript, label it with the same pipeline as the CLI, and show the evidence.

Run from the project root:  streamlit run frontend_streamlitapp/app.py
"""

from datetime import datetime
from pathlib import Path
import sys

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))  # Import the labeler package from the project root.

from labeler.data import read_jsonl, validated_calls
from labeler.labels import IST
from labeler.providers import DEFAULT_MODEL, api_key, model_settings
from labeler.runner import label_call, load_env, sanitized

DEMO = PROJECT_ROOT / "examples" / "demo_call.jsonl"


def load_prompts():
    return {
        name: (PROJECT_ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")
        for name in ("first_pass", "follow_up")
    }


def cited_quotes(row):
    """(answer, turn, quote) for every model answer that cites the transcript."""
    first, second = row["first_pass"], row["second_pass"] or {}
    answers = {f"outcome: {name}": first["outcome"][name] for name in ("invalid", "refusal", "booking")}
    answers.update({f"second pass: {name}": second[name] for name in ("final_reason", "postponement") if name in second})
    rows = [(name, answer["turn"], answer["quote"]) for name, answer in answers.items() if answer.get("quote")]
    agreement = (second.get("callback") or first["callback"])["agreement"]
    if agreement:
        rows += [("callback proposal", agreement["proposal_turn"], agreement["proposal"]),
                 ("callback acknowledgment", agreement["acknowledgment_turn"], agreement["acknowledgment"])]
    return rows


st.set_page_config(page_title="Call labeler", layout="wide")
st.title("Call labeler")
st.caption("Same pipeline as `label_calls.py predict`: the model answers with quotes, Python applies the workbook rules.")

model = st.selectbox("Model", [DEFAULT_MODEL, "gemini/gemini-3.5-flash-lite"])
started = st.text_input("Call started at (ISO 8601 with +05:30)", datetime.now(IST).isoformat(timespec="seconds"))
transcript = st.text_area("Transcript (one 'Agent:' or 'Customer:' line per turn)",
                          value=next(read_jsonl(DEMO))["transcript"], height=260)

if st.button("Label call", type="primary", disabled=not transcript.strip()):
    load_env()
    try:
        api_key(model)
        call = validated_calls([{"transcript_id": "live", "call_started_at": started,
                                 "timezone": "Asia/Kolkata", "transcript": transcript}])[0]
        with st.spinner("Calling the model (one or two passes)..."):
            prediction, row = label_call(call, model, load_prompts(), model_settings(model))
    except Exception as error:
        # Our ValueErrors (bad key, bad timestamp, sanitized provider errors) are safe to show; others show only their type.
        st.error(f"Labeling failed: {error if isinstance(error, ValueError) else sanitized(error)}")
        st.stop()

    st.subheader("Labels")
    st.table([{field: prediction[field] for field in ("disposition", "sub_disposition", "lead_quality", "next_call_at")}])
    st.write(f"**Rules applied:** {row['rule']}")
    if row.get("note"):
        st.warning(row["note"])
    st.caption(f"Tokens: {row['prompt_tokens']} prompt, {row['completion_tokens']} completion")

    st.subheader("Evidence the model cited")
    st.table([{"answer": name, "turn": turn, "quote": quote} for name, turn, quote in cited_quotes(row)])
    with st.expander("Raw model answers"):
        st.json({"first_pass": row["first_pass"], "second_pass": row["second_pass"]})
