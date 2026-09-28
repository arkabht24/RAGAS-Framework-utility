from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class APIConfig(BaseModel):
    url: str
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=lambda: {"Content-Type": "application/json"})
    auth: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 60
    retries: int = 0


class RequestMapper(BaseModel):
    body_template: dict[str, Any]
    query_params_template: dict[str, Any] = Field(default_factory=dict)


class ResponseMapper(BaseModel):
    answer_path: str
    retrieved_contexts_path: str | None = None
    context_ids_path: str | None = None
    citations_path: str | None = None
    request_id_path: str | None = None
    latency_ms_path: str | None = None
    provider_path: str | None = None
    deployment_path: str | None = None
    model_path: str | None = None
    input_tokens_path: str | None = None
    output_tokens_path: str | None = None
    total_tokens_path: str | None = None
    generation_calls_path: str | None = None


class MetricsConfig(BaseModel):
    groups: list[Literal["retrieval", "generation"]] = Field(default_factory=lambda: ["generation"])
    metrics: list[str] = Field(default_factory=lambda: ["faithfulness", "answer_relevancy", "answer_correctness"])
    thresholds: dict[str, float] = Field(default_factory=dict)


class JudgeConfig(BaseModel):
    provider: Literal["gemini"] = "gemini"
    model: str
    api_key_env: str = "GOOGLE_API_KEY"
    concurrency: int = 2
    timeout_seconds: int = 90
    generate_assessment: bool = True


class ReportingConfig(BaseModel):
    output_dir: str = "rag_eval_results"
    launch_dashboard: bool = False
    redact_raw_api_response: bool = False


class PricingConfig(BaseModel):
    catalog_path: str | None = None
    display_currency: str = "USD"
