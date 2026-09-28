import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_api_eval.mapper import extract, render_template
from rag_api_eval.runner import evaluate_rag
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
