"""Interactive dashboard for runs produced by rag-api-eval."""

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st


def display(value, places=2):
    return round(value, places) if isinstance(value, float) else value


def metric_value(record, metric):
    if record.get("metric_status", {}).get(metric, "").startswith("N/A"):
        return "N/A"
    return display(record.get("metrics", {}).get(metric))


def usage_value(record, field):
    value = record.get("application_usage", {}).get(field)
    return value if value is not None else "Not provided by API"


def cost_value(record):
    value = record.get("application_cost", {}).get("cost")
    return f"${value:.4f}" if isinstance(value, (float, int)) else "N/A"


def threshold_value(record, metric):
    result = record.get("threshold_results", {}).get(metric)
    if not result:
        return "Not configured"
    status = result.get("status", "not_configured")
    return {"pass": "Pass", "fail": "Fail", "not_applicable": "N/A"}.get(status, "Not configured")


def main() -> None:
    st.set_page_config(page_title="RAG API Evaluation", page_icon="🧪", layout="wide")
    st.markdown("<style>.block-container { max-width: 1400px; padding-top: 2.5rem; }</style>", unsafe_allow_html=True)
    st.title("🧪 RAG API Evaluation Dashboard")
    st.caption("Retrieval quality, generation quality, application telemetry, cost, and concise LLM Judge assessments.")
    results_dir = Path(os.getenv("RAG_EVAL_RESULTS_DIR", "rag_eval_results"))
    runs = sorted((path for path in results_dir.glob("*") if (path / "summary.json").exists()), reverse=True)
    if not runs:
        st.info("No evaluation runs found in ./rag_eval_results.")
        return
    if st.button("Refresh runs"):
        st.rerun()
    run = st.selectbox("Evaluation run", runs, format_func=lambda value: value.name)
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    records = json.loads((run / "cases.json").read_text(encoding="utf-8"))
    successful = [record for record in records if "error" not in record]
    metrics = sorted({metric for record in successful for metric in record.get("metrics", {})})

    cards = st.columns(6)
    cards[0].metric("Test cases", summary.get("case_count", len(records)))
    cards[1].metric("Successful API calls", f"{summary.get('successful_cases', len(successful))}/{len(records)}")
    judge = summary.get("judge", {})
    passes = judge.get("passes")
    faithfulness = [record.get("metrics", {}).get("faithfulness") for record in successful]
    faithfulness = [value for value in faithfulness if isinstance(value, (float, int))]
    threshold_summary = summary.get("threshold_verdicts", {})
    cards[2].metric("Threshold passes", f"{threshold_summary.get('passes', 0)}/{len(successful)}" if summary.get("thresholds") else "Not configured")
    cards[3].metric("Judge passes", f"{passes}/{len(successful)}" if passes is not None else "Not configured")
    cards[4].metric("Avg. faithfulness", f"{sum(faithfulness) / len(faithfulness):.2f}" if faithfulness else "N/A")
    total_cost = summary.get("application_cost", {}).get("cost")
    cards[5].metric("Application cost", f"${total_cost:.4f}" if isinstance(total_cost, (float, int)) else "N/A")
    token_cards = st.columns(3)
    token_usage = summary.get("application_usage", {})
    token_cards[0].metric("Input tokens", token_usage.get("input_tokens") if token_usage.get("input_tokens") is not None else "Not provided by API")
    token_cards[1].metric("Output tokens", token_usage.get("output_tokens") if token_usage.get("output_tokens") is not None else "Not provided by API")
    token_cards[2].metric("Total tokens", token_usage.get("total_tokens") if token_usage.get("total_tokens") is not None else "Not provided by API")
    if judge.get("model"):
        st.caption(f"Judge: {judge['provider']} / {judge['model']} · Run: {summary.get('run_id')}")

    rows = []
    for record in records:
        rows.append({
            "Case": record.get("id"), "API status": "error" if record.get("error") else "ok",
            "Threshold verdict": record.get("threshold_verdict", "Not configured").replace("_", " ").title(),
            "Judge verdict": record.get("judge_assessment", {}).get("status", "Not configured"),
            **{metric.replace("_", " ").title(): metric_value(record, metric) for metric in metrics},
            "Model": usage_value(record, "model"),
            "Input tokens": usage_value(record, "input_tokens"),
            "Output tokens": usage_value(record, "output_tokens"),
            "Total tokens": usage_value(record, "total_tokens"),
            "App cost": cost_value(record), "Latency (ms)": record.get("latency_ms", "Not provided by API"),
        })
    frame = pd.DataFrame(rows)
    verdicts = sorted(frame["Threshold verdict"].dropna().unique().tolist())
    selected = st.multiselect("Filter threshold verdict", verdicts, default=verdicts)
    st.dataframe(frame[frame["Threshold verdict"].isin(selected)], use_container_width=True, hide_index=True)

    case_id = st.selectbox("Inspect a test case", [record.get("id") for record in records])
    record = next(item for item in records if item.get("id") == case_id)
    assessment = record.get("judge_assessment", {})
    left, right = st.columns(2)
    with left:
        st.subheader("Question and response")
        st.markdown("**Question**")
        st.write(record.get("question"))
        st.markdown("**System answer**")
        st.write(record.get("answer", record.get("error", "No answer returned.")))
        st.markdown("**Reference answer**")
        st.write(record.get("reference_answer") or "Not provided by dataset.")
    with right:
        st.subheader("LLM Judge assessment")
        if assessment:
            st.metric("Verdict", assessment.get("status", "needs_review").replace("_", " ").title())
            st.markdown("**Rationale**")
            st.write(assessment.get("rationale", "No rationale returned."))
            st.markdown("**Evidence used**")
            st.write(assessment.get("evidence_used") or "None reported.")
            st.markdown("**Issues found**")
            st.write(assessment.get("issues") or "None reported.")
        else:
            st.info("No LLM Judge assessment was configured for this run.")

    st.subheader("Metric scores and thresholds")
    st.dataframe(pd.DataFrame({
        "Metric": [item.replace("_", " ").title() for item in metrics],
        "Score": [metric_value(record, item) for item in metrics],
        "Threshold": [record.get("threshold_results", {}).get(item, {}).get("threshold", "Not configured") for item in metrics],
        "Threshold result": [threshold_value(record, item) for item in metrics],
    }), use_container_width=True, hide_index=True)
    st.subheader("Application usage and cost")
    st.json({"usage": record.get("application_usage", {"message": "Token consumption information is not present in the API response."}), "cost": record.get("application_cost", {"cost": None})})
    with st.expander("Retrieved contexts"):
        contexts = record.get("retrieved_contexts", [])
        if contexts:
            for index, context in enumerate(contexts, 1):
                st.markdown(f"**Context {index}**")
                st.text(context)
        else:
            st.write("No retrieved contexts were provided by the API.")
    with st.expander("Raw normalized result"):
        st.json(record)


if __name__ == "__main__":
    main()
