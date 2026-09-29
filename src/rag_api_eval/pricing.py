from __future__ import annotations

import json


def calculate_cost(usage: dict, catalog: dict | None = None) -> dict:
    if usage.get("status") != "available":
        return {"status": "unavailable", "cost": None, "message": usage.get("message")}
    if usage.get("deployment") == "local" or usage.get("provider") == "ollama":
        return {"status": "local", "cost": 0.0, "currency": "USD", "message": "Local infrastructure cost is not calculated."}
    try:
        entry = (catalog or {})[usage["provider"]][usage["model"]]
        input_rate = float(entry["input_per_million_tokens"])
        output_rate = float(entry["output_per_million_tokens"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"status": "unavailable", "cost": None, "message": "No pricing entry was supplied for the API model."}
    input_cost = usage["input_tokens"] * input_rate / 1_000_000
    output_cost = usage["output_tokens"] * output_rate / 1_000_000
    return {
        "status": "available", "cost": round(input_cost + output_cost, 8),
        "input_cost": round(input_cost, 8), "output_cost": round(output_cost, 8),
        "currency": entry.get("currency", "USD"), "pricing": entry,
    }
