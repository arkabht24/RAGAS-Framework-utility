"""Optional application telemetry normalization and missing-data explanations."""

from __future__ import annotations

from typing import Any


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def normalize_usage(values: dict[str, Any]) -> dict[str, Any]:
    usage = {
        "provider": values.get("provider") if isinstance(values.get("provider"), str) else None,
        "deployment": values.get("deployment") if isinstance(values.get("deployment"), str) else None,
        "model": values.get("model") if isinstance(values.get("model"), str) else None,
        "input_tokens": _number(values.get("input_tokens")),
        "output_tokens": _number(values.get("output_tokens")),
        "total_tokens": _number(values.get("total_tokens")),
        "generation_calls": _number(values.get("generation_calls")),
    }
    reasons = []
    if not usage["model"]:
        reasons.append("Model information is not present in the API response.")
    if usage["input_tokens"] is None or usage["output_tokens"] is None:
        reasons.append("Token consumption information is not present in the API response.")
    if not reasons:
        usage["status"] = "available"
        usage["message"] = "Application usage telemetry received."
    else:
        usage["status"] = "partial" if any(usage[key] is not None for key in ("input_tokens", "output_tokens", "total_tokens")) else "missing"
        usage["message"] = " ".join(reasons)
    return usage
