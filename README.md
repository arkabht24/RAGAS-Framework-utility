# rag-api-eval

`rag-api-eval` evaluates a RAG application through its HTTP API. It maps an
arbitrary request/response contract into a normalized record, runs selected
RAGAS metrics, preserves optional application telemetry, calculates model cost
from caller-supplied prices, applies metric thresholds, and writes
dashboard-ready results.

See the [complete user guide](docs/USAGE.md) for configuration reference,
examples, output formats, dashboard instructions, and troubleshooting.

## Install

```bash
pip install .
```

All runtime dependencies, including RAGAS and Streamlit, are installed by the
package metadata. Configure a judge key (for example `GOOGLE_API_KEY`) before
running LLM-judged metrics.

From the evaluated project's root, launch its results dashboard with:

```bash
rag-eval
```

The command opens the bundled dashboard for `./rag_eval_results`. This is also
the default directory used by `evaluate_rag`.

## Minimal use

```python
from rag_api_eval import evaluate_rag

evaluate_rag(
    api_config={"url": "http://127.0.0.1:8000/v1/analyses"},
    dataset="golden.jsonl",
    request_mapper={"body_template": {"question": "{{ question }}"}},
    response_mapper={"answer_path": "$.answer"},
    metrics_config={"groups": ["generation"], "metrics": ["answer_relevancy"]},
    judge_config={"provider": "gemini", "model": "gemini-3.6-flash", "api_key_env": "GOOGLE_API_KEY"},
)
```

To run retrieval or faithfulness metrics, map retrieved evidence:

```python
response_mapper={
    "answer_path": "$.answer",
    "retrieved_contexts_path": "$.trace.retrieved_contexts[*].text",
    "model_path": "$.application_usage.model",
    "input_tokens_path": "$.application_usage.input_tokens",
    "output_tokens_path": "$.application_usage.output_tokens",
}
```

Missing optional telemetry never fails an evaluation. The dashboard reports the
field as not received and marks cost as `N/A`.

## Metric thresholds

Configure deterministic pass/fail thresholds alongside the requested metrics:

```python
metrics_config={
    "metrics": ["faithfulness", "answer_relevancy"],
    "thresholds": {
        "faithfulness": 0.8,
        "answer_relevancy": 0.7
    }
}
```

A case passes when every applicable configured metric meets its threshold and
fails when any applicable metric is below its threshold. Metrics that return
`N/A` are marked not applicable and do not cause a failure. Threshold verdicts
are saved in the result files and displayed in the dashboard.

## Application pricing

Pass application-model pricing from the caller; the package does not embed or
scrape provider rates:

```python
pricing_config={
    "catalog": {
        "gemini": {
            "gemini-3.6-flash": {
                "currency": "USD",
                "input_per_million_tokens": 0.75,
                "output_per_million_tokens": 3.75
            }
        }
    }
}
```

If no matching provider/model entry is supplied, cost is reported as `N/A`.
