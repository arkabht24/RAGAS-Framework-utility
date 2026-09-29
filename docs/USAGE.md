# RAG API Evaluation Utility: User Guide

`rag-api-eval` evaluates a RAG application through its HTTP API. It sends each
question in an evaluation dataset to the API, converts the API response into a
consistent record, optionally calculates RAGAS metrics and an LLM judge verdict,
estimates application model cost, and saves results for a Streamlit dashboard.

The utility treats the RAG application as a black box. The application can use
any framework or internal architecture as long as it exposes an HTTP endpoint
that accepts JSON and returns a JSON object.

## 1. Installation

The package requires Python 3.10 or newer.

From the repository root, install it with:

```bash
pip install .
```

For editable local development:

```bash
pip install -e .
```

LLM-based evaluation currently uses Gemini. Set the API key before requesting
RAGAS metrics or an LLM judge assessment:

```bash
export GOOGLE_API_KEY="your-key"
```

An API-only run with no metrics and no judge does not require this key.

## 2. Quick start

Create a JSON Lines dataset named `golden.jsonl`:

```json
{"id":"case-001","question":"What is RAG?","reference_answer":"RAG combines information retrieval with language-model generation."}
{"id":"case-002","question":"Why is grounding useful?","reference_answer":"Grounding helps answers rely on relevant external evidence."}
```

Then create and run a Python script:

```python
from rag_api_eval import evaluate_rag

summary = evaluate_rag(
    api_config={
        "url": "http://127.0.0.1:8000/v1/answer",
    },
    dataset="golden.jsonl",
    request_mapper={
        "body_template": {
            "question": "{{ question }}",
        }
    },
    response_mapper={
        "answer_path": "$.answer",
        "retrieved_contexts_path": "$.contexts[*].text",
    },
    metrics_config={
        "metrics": [],
    },
)

print(summary)
```

This example calls the target API and writes normalized results without using an
LLM judge. Results are saved under:

```text
rag_eval_results/<UTC-run-timestamp>/
```

## 3. Evaluation flow

For every dataset case, the utility performs the following operations:

1. Validates the supplied configuration.
2. Replaces request placeholders with values from the dataset case.
3. Sends an HTTP request to the configured RAG API.
4. Extracts fields from the JSON response using JSONPath expressions.
5. Normalizes the answer, contexts, metadata, and usage telemetry.
6. Calculates application cost when model and token data are available.
7. Runs requested RAGAS metrics on successful cases.
8. Optionally asks an LLM judge for a concise verdict.
9. Saves case-level results, a run summary, and a configuration snapshot.

An API or mapping failure is normally recorded against the affected case. It
does not prevent the remaining dataset cases from being sent to the API.

## 4. Dataset format

`dataset` may be one of the following:

- A path to a `.jsonl` file containing one JSON object per non-empty line.
- A path to a JSON file containing a top-level array.
- A Python list of dictionaries.

Every case must contain a text `question`:

```json
{
  "id": "case-001",
  "question": "What is retrieval-augmented generation?",
  "reference_answer": "RAG retrieves relevant information before generating an answer.",
  "tenant": {
    "id": "acme"
  }
}
```

Fields have these roles:

| Field | Required | Purpose |
|---|---:|---|
| `question` | Yes | Input question and RAGAS user input. |
| `id` | No | Stable identifier shown in result files and the dashboard. |
| `reference_answer` | No | Ground-truth answer needed by some metrics. |
| Any other field | No | May be referenced from request templates. |

When `id` is omitted, the utility generates a process-specific identifier. For
repeatable reporting, provide an explicit unique `id` for every case.

## 5. API configuration

`api_config` defines how the evaluated endpoint is called:

```python
api_config = {
    "url": "https://rag.example.com/v1/answer",
    "method": "POST",
    "headers": {
        "Content-Type": "application/json",
        "X-Tenant": "acme",
    },
    "auth": {
        "type": "bearer",
        "token_env": "RAG_API_TOKEN",
    },
    "timeout_seconds": 60,
}
```

| Option | Default | Description |
|---|---|---|
| `url` | None | Required endpoint URL. |
| `method` | `POST` | HTTP method sent through `requests`. |
| `headers` | `Content-Type: application/json` | Static request headers. |
| `auth` | `{}` | Authentication configuration. |
| `timeout_seconds` | `60` | Per-request HTTP timeout. |
| `retries` | `0` | Accepted by configuration, but retries are not implemented yet. |

### Authentication

No authentication:

```python
"auth": {"type": "none"}
```

Bearer token from an environment variable:

```python
"auth": {
    "type": "bearer",
    "token_env": "RAG_API_TOKEN",
}
```

API key in a custom header:

```python
"auth": {
    "type": "api_key",
    "header": "X-API-Key",
    "token_env": "RAG_API_KEY",
}
```

A literal `token` can be supplied instead of `token_env`, but environment
variables are safer because the original API configuration is written to the
run's configuration snapshot.

## 6. Request mapping

The request mapper converts a dataset case into the API's expected request.

```python
request_mapper = {
    "body_template": {
        "messages": [
            {
                "role": "user",
                "content": "{{ question }}",
            }
        ],
        "tenant_id": "{{ tenant.id }}",
        "top_k": 5,
    },
    "query_params_template": {
        "environment": "evaluation",
        "case": "{{ id }}",
    },
}
```

This can produce an HTTP request equivalent to:

```text
POST /v1/answer?environment=evaluation&case=case-001
```

with this JSON body:

```json
{
  "messages": [
    {"role": "user", "content": "What is retrieval-augmented generation?"}
  ],
  "tenant_id": "acme",
  "top_k": 5
}
```

Placeholders may use dot-separated paths such as `{{ tenant.id }}`. A value made
entirely of one placeholder retains its original type. For example, a dataset
integer remains an integer. A placeholder embedded in other text is converted
to a string.

Missing template fields produce an error for that case. Templates perform only
field lookup and substitution; they do not execute code or expressions.

## 7. Response mapping

The response mapper uses JSONPath expressions to translate the API's response
into the utility's normalized schema.

Suppose the API returns:

```json
{
  "result": {
    "answer": "RAG retrieves relevant information before generation.",
    "contexts": [
      {"id": "doc-1", "text": "RAG combines retrieval and generation."},
      {"id": "doc-2", "text": "Retrieved evidence is added to the prompt."}
    ],
    "citations": ["https://example.com/rag"]
  },
  "metadata": {
    "request_id": "req-123",
    "latency_ms": 410
  },
  "usage": {
    "provider": "gemini",
    "deployment": "cloud",
    "model": "gemini-3.6-flash",
    "input_tokens": 1000,
    "output_tokens": 200,
    "total_tokens": 1200,
    "generation_calls": 1
  }
}
```

Use this mapper:

```python
response_mapper = {
    "answer_path": "$.result.answer",
    "retrieved_contexts_path": "$.result.contexts[*].text",
    "context_ids_path": "$.result.contexts[*].id",
    "citations_path": "$.result.citations[*]",
    "request_id_path": "$.metadata.request_id",
    "latency_ms_path": "$.metadata.latency_ms",
    "provider_path": "$.usage.provider",
    "deployment_path": "$.usage.deployment",
    "model_path": "$.usage.model",
    "input_tokens_path": "$.usage.input_tokens",
    "output_tokens_path": "$.usage.output_tokens",
    "total_tokens_path": "$.usage.total_tokens",
    "generation_calls_path": "$.usage.generation_calls",
}
```

Only `answer_path` is required. It must resolve to text. All other paths are
optional.

Use wildcard paths for repeated fields, such as:

```text
$.result.contexts[*].text
```

This produces a flat list of matches. A path resolving to the entire context
array can instead produce a nested list and will not be treated as text context.

## 8. Metrics and judge configuration

The available metric names are:

| Metric | Retrieved contexts required | Reference answer required |
|---|---:|---:|
| `faithfulness` | Yes | No |
| `context_precision` | Yes | Yes |
| `context_recall` | Yes | Yes |
| `answer_relevancy` | No | No |
| `answer_correctness` | No | Yes |

Configure metrics and the Gemini judge as follows:

```python
metrics_config = {
    "metrics": [
        "faithfulness",
        "answer_relevancy",
        "answer_correctness",
    ]
}

judge_config = {
    "provider": "gemini",
    "model": "gemini-3.6-flash",
    "api_key_env": "GOOGLE_API_KEY",
    "concurrency": 2,
    "timeout_seconds": 90,
    "generate_assessment": True,
}
```

When any metric is selected, `judge_config` is required. Metrics that lack the
necessary contexts or reference answer are marked `N/A` for the affected case.

`answer_relevancy` and `answer_correctness` additionally use the
`gemini-embedding-001` embedding model.

The separate judge assessment assigns one of these case-level verdicts:

- `pass`
- `fail`
- `needs_review`

It also stores a concise rationale, supporting evidence, and a list of issues.
Set `generate_assessment` to `False` to calculate RAGAS metrics without this
additional assessment.

### Running without metrics or a judge

To exercise the API, normalize responses, and collect telemetry only:

```python
metrics_config = {"metrics": []}
```

Omit `judge_config` in this mode.

### Thresholds

Configure deterministic pass/fail thresholds by metric name:

```python
metrics_config = {
    "metrics": ["faithfulness", "answer_relevancy"],
    "thresholds": {
        "faithfulness": 0.8,
        "answer_relevancy": 0.7,
    },
}
```

Each configured threshold produces a `threshold_results` entry containing the
metric score, configured threshold, and one of these statuses:

- `pass`: the numeric score is greater than or equal to the threshold.
- `fail`: the numeric score is below the threshold.
- `not_applicable`: the metric is `N/A` or has no numeric score.

The case-level `threshold_verdict` is `fail` if any applicable threshold fails,
`pass` if all applicable thresholds pass, and `not_applicable` when none of the
configured thresholds has a usable score. When no thresholds are configured,
the verdict is `not_configured`.

Threshold verdicts are deterministic and separate from the LLM judge verdict.
They are saved in `cases.json`, aggregated in `summary.json`, and displayed in
the dashboard. A failed threshold does not raise an exception or stop the run.

The `groups` setting is accepted but is not currently used to select metrics.

## 9. Usage telemetry and cost

Telemetry is optional. To calculate cost, the API response must provide:

- Model name
- Input-token count
- Output-token count
- A provider and model that match a caller-supplied pricing entry

Token values must be non-negative integers. Missing or invalid information is
recorded as `missing` or `partial`, and cost is shown as unavailable. It does not
fail the evaluation.

If `deployment` is `local` or `provider` is `ollama`, the reported model cost is
zero and local infrastructure cost is explicitly excluded.

### Caller-supplied pricing catalog

The package does not embed or scrape provider prices. Supply the prices to use
for the run directly in `pricing_config`:

```python
pricing_config = {
    "catalog": {
        "gemini": {
            "gemini-3.6-flash": {
                "currency": "USD",
                "input_per_million_tokens": 0.75,
                "output_per_million_tokens": 3.75,
            }
        }
    }
}
```

The catalog has this structure:

```json
{
  "provider-name": {
    "model-name": {
      "currency": "USD",
      "input_per_million_tokens": 0.5,
      "output_per_million_tokens": 1.5
    }
  }
}
```

Cost is calculated as:

```text
(input tokens × input rate + output tokens × output rate) / 1,000,000
```

The `display_currency` option is accepted but does not currently convert
currencies. If the catalog is empty or has no matching provider/model entry,
usage remains available but application cost is reported as unavailable.

## 10. Reporting configuration

```python
reporting_config = {
    "output_dir": "rag_eval_results",
    "launch_dashboard": False,
    "redact_raw_api_response": True,
}
```

| Option | Default | Description |
|---|---|---|
| `output_dir` | `rag_eval_results` | Parent directory for timestamped runs. |
| `launch_dashboard` | `False` | Starts Streamlit after saving the run. |
| `redact_raw_api_response` | `False` | Replaces stored raw API responses with `null`. |

Enable redaction if the target response can contain private, sensitive, or
unnecessary information. Normalized fields such as answers and contexts are
still saved, so review those fields separately when handling sensitive data.

## 11. Complete evaluation example

```python
from rag_api_eval import evaluate_rag

summary = evaluate_rag(
    api_config={
        "url": "https://rag.example.com/v1/answer",
        "method": "POST",
        "auth": {
            "type": "bearer",
            "token_env": "RAG_API_TOKEN",
        },
        "timeout_seconds": 60,
    },
    dataset="golden.jsonl",
    request_mapper={
        "body_template": {
            "question": "{{ question }}",
        },
        "query_params_template": {
            "evaluation": "true",
        },
    },
    response_mapper={
        "answer_path": "$.result.answer",
        "retrieved_contexts_path": "$.result.contexts[*].text",
        "context_ids_path": "$.result.contexts[*].id",
        "citations_path": "$.result.citations[*]",
        "request_id_path": "$.metadata.request_id",
        "latency_ms_path": "$.metadata.latency_ms",
        "provider_path": "$.usage.provider",
        "deployment_path": "$.usage.deployment",
        "model_path": "$.usage.model",
        "input_tokens_path": "$.usage.input_tokens",
        "output_tokens_path": "$.usage.output_tokens",
        "total_tokens_path": "$.usage.total_tokens",
        "generation_calls_path": "$.usage.generation_calls",
    },
    metrics_config={
        "metrics": [
            "context_precision",
            "context_recall",
            "faithfulness",
            "answer_relevancy",
            "answer_correctness",
        ],
        "thresholds": {
            "faithfulness": 0.8,
            "answer_relevancy": 0.7,
        },
    },
    judge_config={
        "provider": "gemini",
        "model": "gemini-3.6-flash",
        "api_key_env": "GOOGLE_API_KEY",
        "concurrency": 2,
        "timeout_seconds": 90,
        "generate_assessment": True,
    },
    pricing_config={
        "catalog": {
            "gemini": {
                "gemini-3.6-flash": {
                    "currency": "USD",
                    "input_per_million_tokens": 0.75,
                    "output_per_million_tokens": 3.75,
                }
            }
        }
    },
    reporting_config={
        "output_dir": "rag_eval_results",
        "redact_raw_api_response": True,
    },
)

print(f"Successful cases: {summary['successful_cases']}")
print(f"Failed cases: {summary['failed_cases']}")
print(f"Results: {summary['run_dir']}")
```

## 12. Output files

Each run creates:

```text
rag_eval_results/
└── 2026-09-29T10-30-00Z/
    ├── cases.json
    ├── summary.json
    └── config_snapshot.json
```

### `cases.json`

Contains one normalized record per dataset case, including:

- Question, reference, and API answer
- Retrieved contexts, IDs, and citations
- Request ID and latency
- Usage and application cost
- RAGAS scores and availability messages
- Per-metric threshold results and a case-level threshold verdict
- LLM judge assessment
- Raw API response, unless redacted
- Error message for failed cases

### `summary.json`

Contains aggregate run information:

- Total, successful, and failed case counts
- Requested metric names
- Configured thresholds and aggregate pass/fail/not-applicable counts
- Input, output, and total token counts
- Sum of known application costs
- Judge provider and model
- Count of judge passes

The `run_dir` value is returned by `evaluate_rag()` but is not written into the
on-disk summary file.

### `config_snapshot.json`

Stores the API configuration, request and response mappers, metrics
configuration, and pricing configuration. It currently does not store the judge
or reporting configuration.

## 13. Dashboard

From the directory containing `rag_eval_results`, run:

```bash
rag-eval
```

or:

```bash
rag-api-eval-dashboard
```

To read results from another directory:

```bash
export RAG_EVAL_RESULTS_DIR="/path/to/results"
rag-eval
```

The dashboard displays:

- Case and API-success counts
- Threshold pass count and threshold-verdict filtering
- Judge pass count
- Average faithfulness
- Token usage and application cost
- A filterable case table with metric and threshold outcomes
- Per-case answers, references, metrics, judge rationale, contexts, and raw data

The dashboard is read-only. It does not execute a new evaluation.

## 14. Error behavior

These failures become case-level error records, allowing later cases to run:

- Missing request-template fields
- Network and HTTP errors
- Non-JSON API responses
- API responses whose top-level value is not an object
- Missing or non-text mapped answers

These failures can stop the overall evaluation:

- Invalid configuration
- Missing or malformed dataset files
- Empty datasets
- Dataset cases without a text `question`
- Requested metrics without a `judge_config`
- Missing judge API key
- Missing RAGAS dependencies
- Failure to create the output directory

Failures while generating an individual LLM assessment are converted to a
`needs_review` assessment for that case.

## 15. Troubleshooting

### `answer_path ... did not resolve to text`

Verify that `answer_path` points to a string rather than an enclosing object or
array. For example, prefer:

```text
$.result.answer
```

over:

```text
$.result
```

### Retrieved-context metrics show `N/A`

Map the actual context text and use a wildcard when the API returns an array:

```python
"retrieved_contexts_path": "$.result.contexts[*].text"
```

### Correctness or recall metrics show `N/A`

Add `reference_answer` to the affected dataset cases.

### Cost shows `N/A`

Check that model, input-token, output-token, and provider paths are mapped and
that `pricing_config.catalog` contains the exact provider/model pair returned by
the API.

### Judge API key is not set

Export the environment variable named by `judge_config.api_key_env`:

```bash
export GOOGLE_API_KEY="your-key"
```

### No runs appear in the dashboard

Launch the dashboard from the directory containing `rag_eval_results`, or set
`RAG_EVAL_RESULTS_DIR` to the correct parent directory.

### A run-directory creation error occurs

Run IDs have one-second precision. Starting two evaluations in the same output
directory during the same second can cause a directory-name collision. Wait one
second or use separate output directories.

## 16. Current limitations

- Only Gemini is supported as the judge provider.
- HTTP retries are configured but not implemented.
- Metric groups are stored but do not select metrics.
- Unknown metric names are silently skipped.
- Display-currency conversion is not implemented.
- Evaluation API calls are made sequentially.
- Judge usage and cost are not included in application usage and cost totals.
- Pricing must be supplied by the caller; the package does not maintain rates.
- Run directory names have one-second timestamp precision.
