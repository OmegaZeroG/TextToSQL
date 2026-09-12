import os

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Text-to-SQL", page_icon="🗄️", layout="wide")

st.title("🗄️ Text-to-SQL with Guardrails")
st.caption(
    "Ask a question in plain English. The generated SQL runs read-only, is checked for "
    "unsafe statements, and comes with a confidence score based on hallucination checks."
)

if "history" not in st.session_state:
    st.session_state.history = []

with st.sidebar:
    st.header("Database schema")
    try:
        schema_resp = requests.get(f"{API_URL}/v1/schema", timeout=10)
        schema_resp.raise_for_status()
        st.code(schema_resp.json()["schema"], language="text")
    except Exception as exc:
        st.error(f"Could not reach backend at {API_URL}: {exc}")

    st.header("Try asking")
    st.markdown(
        "- How many orders were placed in 2024?\n"
        "- Who are the top 5 customers by total spend?\n"
        "- What's the average order value by city?\n"
        "- Show me discontinued products that still have pending orders\n"
        "- DROP TABLE orders *(try this — it gets blocked)*"
    )

question = st.text_input("Your question", placeholder="e.g. What are the top 5 best-selling products?")
submit = st.button("Ask", type="primary")

if submit and question.strip():
    with st.spinner("Generating SQL and validating..."):
        try:
            resp = requests.post(f"{API_URL}/v1/query", json={"question": question}, timeout=60)
        except Exception as exc:
            st.error(f"Request failed: {exc}")
            resp = None

    if resp is not None:
        if resp.status_code == 422:
            detail = resp.json().get("detail", {})
            st.warning(detail.get("message", "This question is ambiguous."))
            for interp in detail.get("interpretations", []):
                st.markdown(f"- {interp}")
        elif resp.status_code >= 400:
            st.error(f"Error: {resp.json().get('detail', resp.text)}")
        else:
            data = resp.json()
            st.session_state.history.insert(0, data)

if st.session_state.history:
    latest = st.session_state.history[0]

    if latest.get("guardrail_blocked"):
        st.error(f"🚫 Blocked by guardrails: {latest['block_reason']}")
        st.code(latest["sql"], language="sql")
    else:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader("Generated SQL")
            st.code(latest["sql"], language="sql")
            st.caption(latest["explanation"])
        with col2:
            conf = latest["confidence"]["overall"]
            color = "🟢" if conf >= 0.75 else "🟡" if conf >= 0.5 else "🔴"
            st.metric("Confidence", f"{color} {conf:.0%}")
            st.caption(f"Back-translation alignment: {latest['confidence']['back_translation_alignment']:.0%}")
            st.caption(f"Result sanity check: {'passed' if latest['confidence']['result_sanity_passed'] else 'flagged'}")
            st.caption(f"{latest['execution_time_ms']} ms · {latest['row_count']} rows")

        for warning in latest.get("warnings", []):
            st.warning(warning)

        if latest["rows"]:
            df = pd.DataFrame(latest["rows"], columns=latest["columns"])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Query executed successfully but returned no rows.")

    st.divider()
    st.subheader("History")
    for entry in st.session_state.history[1:6]:
        with st.expander(entry["question"]):
            st.code(entry.get("sql", ""), language="sql")
