"""RAGAS metric adapter. Imports are deferred so API-only runs stay lightweight."""

from __future__ import annotations

import os
import sys
import types
import json
from typing import Any


class EvaluationMetricError(RuntimeError):
    pass


class _LegacyEmbeddingAdapter:
    """Bridge current RAGAS embeddings to legacy metric method names."""

    def __init__(self, embeddings):
        self._embeddings = embeddings

    def __getattr__(self, name):
        return getattr(self._embeddings, name)

    def embed_query(self, text: str):
        return self._embeddings.embed_text(text)

    def embed_documents(self, texts: list[str]):
        return self._embeddings.embed_texts(texts)

    async def aembed_query(self, text: str):
        return await self._embeddings.aembed_text(text)

    async def aembed_documents(self, texts: list[str]):
        return await self._embeddings.aembed_texts(texts)


def _install_ragas_compatibility_shim() -> None:
    """Support RAGAS 0.4 when LangChain has removed its VertexAI module."""
    try:
        from langchain_community.chat_models.vertexai import ChatVertexAI  # noqa: F401
    except ModuleNotFoundError:
        from langchain_google_genai import ChatGoogleGenerativeAI

        module = types.ModuleType("langchain_community.chat_models.vertexai")
        module.ChatVertexAI = ChatGoogleGenerativeAI
        sys.modules[module.__name__] = module


def _judge(config):
    if config.provider != "gemini":
        raise EvaluationMetricError(f"Unsupported judge provider '{config.provider}'.")
    key = os.getenv(config.api_key_env)
    if not key:
        raise EvaluationMetricError(f"Judge API key environment variable '{config.api_key_env}' is not set.")
    try:
        import instructor
        from instructor import Mode
        from openai import OpenAI
        from ragas.llms import llm_factory
    except ImportError as exc:
        raise EvaluationMetricError("RAGAS judge dependencies are not installed.") from exc
    return llm_factory(
        config.model,
        provider="google",
        client=instructor.from_openai(
            OpenAI(api_key=key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/", timeout=config.timeout_seconds),
            mode=Mode.JSON,
        ),
        adapter="litellm",
        temperature=0,
    )


def _embeddings(config):
    import os
    from google import genai
    from ragas.embeddings import GoogleEmbeddings
    key = os.getenv(config.api_key_env)
    return _LegacyEmbeddingAdapter(
        GoogleEmbeddings(client=genai.Client(api_key=key), model="gemini-embedding-001")
    )


def evaluate_records(records: list[dict[str, Any]], requested: list[str], judge_config) -> None:
    """Populate metric scores; unsupported input becomes per-case N/A, never a crash."""
    if not requested:
        return
    _install_ragas_compatibility_shim()
    try:
        from ragas import EvaluationDataset, SingleTurnSample, evaluate
        from ragas.metrics import AnswerCorrectness, AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness
        from ragas.run_config import RunConfig
    except ImportError as exc:
        raise EvaluationMetricError("RAGAS is required for selected metrics.") from exc
    judge = _judge(judge_config)
    embedding_metrics = {"answer_relevancy", "answer_correctness"}
    embeddings = _embeddings(judge_config) if embedding_metrics.intersection(requested) else None
    metric_builders = {
        "context_precision": lambda: ContextPrecision(llm=judge),
        "context_recall": lambda: ContextRecall(llm=judge),
        "faithfulness": lambda: Faithfulness(llm=judge),
        "answer_relevancy": lambda: AnswerRelevancy(llm=judge, embeddings=embeddings),
        "answer_correctness": lambda: AnswerCorrectness(llm=judge, embeddings=embeddings),
    }
    config = RunConfig(timeout=judge_config.timeout_seconds, max_workers=judge_config.concurrency)
    for metric_name in requested:
        builder = metric_builders.get(metric_name)
        if builder is None:
            continue
        indexes = []
        samples = []
        for index, record in enumerate(records):
            needs_context = metric_name in {"context_precision", "context_recall", "faithfulness"}
            needs_reference = metric_name in {"context_precision", "context_recall", "answer_correctness"}
            if needs_context and not record["retrieved_contexts"]:
                record["metric_status"][metric_name] = "N/A — retrieved contexts were not provided by the API."
                continue
            if needs_reference and not record.get("reference_answer"):
                record["metric_status"][metric_name] = "N/A — reference answer was not provided by the dataset."
                continue
            indexes.append(index)
            samples.append(SingleTurnSample(user_input=record["question"], response=record["answer"], retrieved_contexts=record["retrieved_contexts"], reference=record.get("reference_answer")))
        if not samples:
            continue
        rows = evaluate(EvaluationDataset(samples=samples), metrics=[builder()], run_config=config, raise_exceptions=False).to_pandas().to_dict(orient="records")
        for index, row in zip(indexes, rows):
            records[index]["metrics"][metric_name] = row.get(metric_name)
            records[index]["metric_status"][metric_name] = "available" if row.get(metric_name) is not None else "N/A — RAGAS returned no score."


def _response_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item if isinstance(item, str) else item.get("text", "") for item in content if isinstance(item, (str, dict)))
    return str(content)


def _json_object(value: str) -> dict:
    value = value.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object in Judge response.")
    return json.loads(value[start:end + 1])


def assess_records(records: list[dict[str, Any]], config) -> None:
    """Add a concise, auditable LLM verdict without exposing chain-of-thought."""
    if not config.generate_assessment:
        return
    key = os.getenv(config.api_key_env)
    if not key:
        raise EvaluationMetricError(f"Judge API key environment variable '{config.api_key_env}' is not set.")
    from langchain_google_genai import ChatGoogleGenerativeAI

    judge = ChatGoogleGenerativeAI(
        google_api_key=key, model=config.model, temperature=0, request_timeout=config.timeout_seconds,
    )
    for record in records:
        prompt = """You are evaluating a RAG application's answer. Return a concise, evidence-based assessment.
Do not reveal private reasoning or chain-of-thought. Return JSON only:
{{
  "status": "pass" | "fail" | "needs_review",
  "rationale": "at most 80 words",
  "evidence_used": ["up to 3 short facts from retrieved contexts"],
  "issues": ["unsupported, unsafe, or incomplete claims"]
}}

Question: {question}
Reference answer: {reference}
System answer: {answer}
Retrieved contexts: {contexts}
Metric scores: {metrics}
""".format(
            question=record["question"], reference=record.get("reference_answer"), answer=record["answer"],
            contexts=json.dumps(record.get("retrieved_contexts", []), ensure_ascii=False),
            metrics=json.dumps(record.get("metrics", {})),
        )
        try:
            value = _json_object(_response_text(judge.invoke(prompt).content))
            status = value.get("status", "needs_review")
            record["judge_assessment"] = {
                "status": status if status in {"pass", "fail", "needs_review"} else "needs_review",
                "rationale": str(value.get("rationale", "No rationale returned.")).strip(),
                "evidence_used": [str(item) for item in value.get("evidence_used", [])][:3],
                "issues": [str(item) for item in value.get("issues", [])],
            }
        except Exception as exc:
            record["judge_assessment"] = {
                "status": "needs_review", "rationale": "The Judge assessment could not be produced.",
                "evidence_used": [], "issues": [f"Judge error: {type(exc).__name__}: {exc}"],
            }
