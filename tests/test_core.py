import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_api_eval.mapper import extract, render_template
from rag_api_eval.pricing import calculate_cost
from rag_api_eval.runner import _apply_thresholds, evaluate_rag
from rag_api_eval.telemetry import normalize_usage


class CoreTests(unittest.TestCase):
    def test_declarative_mapper_renders_and_extracts(self):
        body = render_template({"messages": [{"content": "{{ question }}"}], "tenant": "{{ tenant.id }}"}, {"question": "Hello", "tenant": {"id": "a"}})
        self.assertEqual(body["messages"][0]["content"], "Hello")
        self.assertEqual(extract({"data": {"answer": "Yes"}}, "$.data.answer"), "Yes")

    def test_missing_token_telemetry_is_explicit(self):
        usage = normalize_usage({"model": "model-a"})
        self.assertEqual(usage["status"], "missing")
        self.assertIn("Token consumption information", usage["message"])

    def test_thresholds_do_not_fail_not_applicable_metrics(self):
        records = [{
            "metrics": {"faithfulness": 0.7},
            "metric_status": {"context_precision": "N/A — context missing."},
        }]
        _apply_thresholds(records, {"faithfulness": 0.8, "context_precision": 0.8})
        self.assertEqual(records[0]["threshold_results"]["faithfulness"]["status"], "fail")
        self.assertEqual(records[0]["threshold_results"]["context_precision"]["status"], "not_applicable")
        self.assertEqual(records[0]["threshold_verdict"], "fail")

    def test_cost_uses_caller_supplied_catalog(self):
        cost = calculate_cost({
            "status": "available", "provider": "gemini", "deployment": "api",
            "model": "demo", "input_tokens": 1_000_000, "output_tokens": 1_000_000,
        }, {"gemini": {"demo": {"currency": "USD", "input_per_million_tokens": 1, "output_per_million_tokens": 2}}})
        self.assertEqual(cost["cost"], 3.0)

    @patch("rag_api_eval.runner.call_api")
    def test_runner_saves_normalized_result_without_judge(self, call_api):
        call_api.return_value = {"payload": {"answer": "A useful answer"}}
        with tempfile.TemporaryDirectory() as directory:
            summary = evaluate_rag(
                api_config={"url": "https://example.test/rag"},
                dataset=[{"id": "case-1", "question": "Question?"}],
                request_mapper={"body_template": {"prompt": "{{ question }}"}},
                response_mapper={"answer_path": "$.payload.answer"},
                metrics_config={"metrics": []},
                reporting_config={"output_dir": directory},
            )
            self.assertEqual(summary["successful_cases"], 1)
            record = json.loads((Path(summary["run_dir"]) / "cases.json").read_text())[0]
            self.assertEqual(record["answer"], "A useful answer")
            self.assertEqual(record["application_usage"]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
