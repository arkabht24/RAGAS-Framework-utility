"""Public black-box API evaluation runner."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import RAGAPIError, call_api
from .mapper import extract, normalize_contexts, render_template
from .metrics import assess_records, evaluate_records
from .models import APIConfig, JudgeConfig, MetricsConfig, PricingConfig, ReportingConfig, RequestMapper, ResponseMapper
from .pricing import calculate_cost
from .telemetry import normalize_usage


def _load_cases(dataset: str | Path | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(dataset, list):
        return dataset
    path = Path(dataset)
    text = path.read_text(encoding="utf-8")
    values = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == ".jsonl" else json.loads(text)
    if not isinstance(values, list):
        raise ValueError("Dataset must contain a JSON array or JSONL records.")
    return values


def _safe(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return value


def _apply_thresholds(records: list[dict], thresholds: dict[str, float]) -> None:
    """Attach deterministic threshold verdicts without treating N/A as failure."""
    for record in records:
        results = {}
        for metric, threshold in thresholds.items():
            score = record.get("metrics", {}).get(metric)
            applicability = record.get("metric_status", {}).get(metric, "")
            if applicability.startswith("N/A") or not isinstance(score, (int, float)):
                results[metric] = {"score": score, "threshold": threshold, "status": "not_applicable"}
            else:
                results[metric] = {
                    "score": score,
                    "threshold": threshold,
                    "status": "pass" if score >= threshold else "fail",
                }
        applicable = [item["status"] for item in results.values() if item["status"] != "not_applicable"]
        record["threshold_results"] = results
        record["threshold_verdict"] = (
            "not_configured" if not thresholds else
            "not_applicable" if not applicable else
            "fail" if "fail" in applicable else "pass"
        )


def _record(case: dict, payload: dict, mapper: ResponseMapper, pricing: PricingConfig, redact: bool) -> dict:
    answer = extract(payload, mapper.answer_path)
    if not isinstance(answer, str):
        raise ValueError(f"answer_path '{mapper.answer_path}' did not resolve to text.")
    raw_usage = {
        "provider": extract(payload, mapper.provider_path), "deployment": extract(payload, mapper.deployment_path),
        "model": extract(payload, mapper.model_path), "input_tokens": extract(payload, mapper.input_tokens_path),
        "output_tokens": extract(payload, mapper.output_tokens_path), "total_tokens": extract(payload, mapper.total_tokens_path),
        "generation_calls": extract(payload, mapper.generation_calls_path),
    }
    usage = normalize_usage(raw_usage)
    return {
        "id": case.get("id", f"case-{id(case)}"), "question": case.get("question"),
        "reference_answer": case.get("reference_answer"), "answer": answer,
        "retrieved_contexts": normalize_contexts(extract(payload, mapper.retrieved_contexts_path, many=True)),
        "context_ids": extract(payload, mapper.context_ids_path, many=True),
        "citations": extract(payload, mapper.citations_path, many=True),
        "request_id": extract(payload, mapper.request_id_path), "latency_ms": extract(payload, mapper.latency_ms_path),
        "application_usage": usage, "application_cost": calculate_cost(usage, pricing.catalog),
        "metrics": {}, "metric_status": {}, "raw_api_response": None if redact else payload,
    }


def evaluate_rag(*, api_config: dict, dataset: str | Path | list[dict], request_mapper: dict,
                 response_mapper: dict, metrics_config: dict | None = None, judge_config: dict | None = None,
                 pricing_config: dict | None = None, reporting_config: dict | None = None) -> dict:
    """Evaluate a RAG HTTP / HTTPS API and return the saved run summary.

    The request/response mappers are declarative. API-specific fields remain at
    the integration edge; all results use a normalized portable schema.
    """
    api = APIConfig.model_validate(api_config)
    request = RequestMapper.model_validate(request_mapper)
    response = ResponseMapper.model_validate(response_mapper)
    metrics = MetricsConfig.model_validate(metrics_config or {})
    pricing = PricingConfig.model_validate(pricing_config or {})
    reporting = ReportingConfig.model_validate(reporting_config or {})
    cases = _load_cases(dataset)
    if not cases:
        raise ValueError("The evaluation dataset is empty.")
    records = []
    for case in cases:
        if not isinstance(case.get("question"), str):
            raise ValueError("Every dataset case must include a text 'question'.")
        try:
            payload = call_api(api, render_template(request.body_template, case), render_template(request.query_params_template, case))
            records.append(_record(case, payload, response, pricing, reporting.redact_raw_api_response))
        except (RAGAPIError, ValueError, KeyError) as exc:
            records.append({"id": case.get("id"), "question": case.get("question"), "reference_answer": case.get("reference_answer"), "error": str(exc), "metrics": {}, "metric_status": {}})
    successful = [record for record in records if "error" not in record]
    judge = JudgeConfig.model_validate(judge_config) if judge_config else None
    if metrics.metrics and successful:
        if judge is None:
            raise ValueError("judge_config is required when RAGAS metrics are selected.")
        evaluate_records(successful, metrics.metrics, judge)
    _apply_thresholds(successful, metrics.thresholds)
    if judge and successful:
        assess_records(successful, judge)
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir = Path(reporting.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    input_total = sum(record.get("application_usage", {}).get("input_tokens") or 0 for record in successful)
    output_total = sum(record.get("application_usage", {}).get("output_tokens") or 0 for record in successful)
    known_costs = [record.get("application_cost", {}).get("cost") for record in successful]
    summary = {
        "run_id": run_id, "case_count": len(records), "successful_cases": len(successful),
        "failed_cases": len(records) - len(successful), "metrics_requested": metrics.metrics,
        "application_usage": {"input_tokens": input_total, "output_tokens": output_total, "total_tokens": input_total + output_total},
        "application_cost": {"cost": round(sum(value for value in known_costs if isinstance(value, (int, float))), 8) if any(isinstance(value, (int, float)) for value in known_costs) else None},
        "judge": {
            "provider": judge.provider if judge else None,
            "model": judge.model if judge else None,
            "passes": sum(record.get("judge_assessment", {}).get("status") == "pass" for record in successful),
        },
        "thresholds": metrics.thresholds,
        "threshold_verdicts": {
            "passes": sum(record.get("threshold_verdict") == "pass" for record in successful),
            "fails": sum(record.get("threshold_verdict") == "fail" for record in successful),
            "not_applicable": sum(record.get("threshold_verdict") == "not_applicable" for record in successful),
        },
    }
    (run_dir / "cases.json").write_text(json.dumps(_safe(records), indent=2), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(_safe(summary), indent=2), encoding="utf-8")
    (run_dir / "config_snapshot.json").write_text(json.dumps({"api_config": api_config, "request_mapper": request_mapper, "response_mapper": response_mapper, "metrics_config": metrics_config, "pricing_config": pricing_config}, indent=2), encoding="utf-8")
    summary["run_dir"] = str(run_dir)
    if reporting.launch_dashboard:
        environment = {**os.environ, "RAG_EVAL_RESULTS_DIR": str(run_dir.parent.resolve())}
        subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("dashboard.py"))], env=environment)
    return summary
