import json
import unittest
from unittest.mock import patch

from codeevo.context_manager import ContextManager
from codeevo.diff_parser import parse_unified_diff
from codeevo.evaluation_benchmark import generate_controlled_pr_cases
from codeevo.evaluation_dataset import (
    DatasetManifest,
    repository_split,
    sha256_text,
    validate_dataset_integrity,
)
from codeevo.evaluation_harness import (
    EndToEndEvaluationHarness,
    comparison_summary,
    validate_case,
)
from codeevo.evaluation_policy import EvaluationPolicy
from codeevo.reviewer import LocalRuleReviewer, OpenAICompatibleReviewer
from codeevo.rollout import RoutingPolicyEvaluator


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


def fake_urlopen(*_args, **_kwargs):
    return FakeResponse({
        "choices": [{"message": {"content": '{"findings": []}'}}],
    })


def public_case(case_id, repository, split, line="safe = True", expected=None):
    diff = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+%s\n" % line
    return {
        "schema_version": 2,
        "id": case_id,
        "repository": repository,
        "pull_request": int(case_id.rsplit("-", 1)[-1]),
        "split": split,
        "source": {
            "kind": "public-github-pr",
            "public_url": "https://github.com/%s/pull/%s" % (
                repository, case_id.rsplit("-", 1)[-1]
            ),
            "api_url": "https://api.github.com/repos/%s/pulls/%s" % (
                repository, case_id.rsplit("-", 1)[-1]
            ),
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "diff_sha256": sha256_text(diff),
            "repository_visibility": "public",
            "license": {
                "spdx_id": "MIT",
                "evidence_url": "https://github.com/%s/blob/main/LICENSE" % repository,
            },
        },
        "annotation": {
            "annotator": "reviewer@example.com",
            "annotated_at": "2026-08-12T00:00:00Z",
            "methodology": "Two-pass changed-line security review",
            "evidence_urls": ["https://github.com/%s/pull/1/files" % repository]
            if expected else [],
        },
        "diff": diff,
        "expected_findings": expected or [],
    }


class EvaluationDatasetTests(unittest.TestCase):
    def test_public_manifest_proves_hashes_and_repository_isolation(self):
        cases = [
            public_case("case-1", "org/one", "validation"),
            public_case("case-2", "org/two", "holdout", "value = 2"),
        ]
        manifest, integrity = DatasetManifest.from_cases(
            cases, "public-pr", "1.0.0", require_public_provenance=True
        )
        self.assertTrue(integrity["valid"])
        self.assertEqual(2, manifest.repositories)
        self.assertEqual({"public-github-pr"}, set(manifest.source_kinds))
        self.assertEqual(64, len(manifest.dataset_sha256))

    def test_integrity_rejects_repository_leakage_and_duplicate_diffs(self):
        first = public_case("case-1", "org/one", "validation")
        second = public_case("case-2", "org/one", "holdout")
        result = validate_dataset_integrity([first, second])
        self.assertFalse(result["valid"])
        self.assertIn("org/one", result["repository_leakage"])
        self.assertTrue(result["duplicate_diffs"])

    def test_repository_split_is_deterministic(self):
        self.assertEqual(
            repository_split("Org/Repo", "stable-salt"),
            repository_split("org/repo", "stable-salt"),
        )


class EvaluationUsageTests(unittest.TestCase):
    def test_harness_supports_train_and_records_local_zero_budget(self):
        case = generate_controlled_pr_cases()[0]
        case["split"] = "train"
        validate_case(case)
        report = EndToEndEvaluationHarness().run(LocalRuleReviewer(), [case])
        self.assertEqual(2, report["schema_version"])
        self.assertEqual(1, report["by_split"]["train"]["cases"])
        self.assertGreaterEqual(report["case_results"][0]["latency_ms"], 0.0)
        usage = report["metrics"]["resource_usage"]
        self.assertEqual("not_applicable", usage["usage_status"])
        self.assertEqual(0, usage["total_tokens"])
        self.assertEqual(0.0, usage["estimated_cost_usd"])

    def test_openai_compatible_reviewer_tracks_provider_usage_and_price(self):
        body = {
            "choices": [{"message": {"content": '{"findings": []}'}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }
        reviewer = OpenAICompatibleReviewer(
            "https://example.test", "key", "model",
            input_cost_per_million=1.0, output_cost_per_million=2.0,
        )
        diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+safe = True\n"
        with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
            reviewer.review(diff, parse_unified_diff(diff))
        usage = reviewer.evaluation_usage()
        self.assertEqual("available", usage["usage_status"])
        self.assertEqual(1, usage["model_calls"])
        self.assertEqual(120, usage["total_tokens"])
        self.assertAlmostEqual(0.00014, usage["estimated_cost_usd"])

    def test_missing_provider_usage_is_reported_unavailable(self):
        body = {"choices": [{"message": {"content": '{"findings": []}'}}]}
        reviewer = OpenAICompatibleReviewer(
            "https://example.test", "key", "model"
        )
        diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+safe = True\n"
        with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
            reviewer.review(diff, parse_unified_diff(diff))
        usage = reviewer.evaluation_usage()
        self.assertEqual("unavailable", usage["token_status"])
        self.assertEqual("unavailable", usage["cost_status"])
        self.assertEqual(1, usage["model_calls"])

    def test_reviewer_bounds_input_output_and_preserves_original_location_validation(self):
        captured = {}
        diff = (
            "--- a/src/App.java\n+++ b/src/App.java\n"
            "@@ -1,2 +1,222 @@\n-old\n"
            "+String query = request.getParameter(\"query\");\n"
            + "".join("+int safe%d = %d;\n" % (index, index) for index in range(220))
        )
        parsed = parse_unified_diff(diff)
        target = parsed.added_lines[0]
        body = {
            "choices": [{"message": {"content": json.dumps({"findings": [{
                "rule_id": "CWE-89", "severity": "high", "title": "SQL injection",
                "explanation": "Untrusted query reaches SQL.", "path": target.path,
                "line": target.line, "evidence": target.content.strip(),
                "fix": "Use a parameterized query.", "test": "Add an injection test.",
                "confidence": 0.9,
            }]})}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
        }

        def capture(request, **_kwargs):
            captured.update(json.loads(request.data.decode("utf-8")))
            return FakeResponse(body)

        reviewer = OpenAICompatibleReviewer(
            "https://example.test", "key", "model",
            context_manager=ContextManager(max_tokens=512, reserved_tokens=64),
            max_output_tokens=321, max_findings=3,
            input_cost_per_million=1.0, output_cost_per_million=1.0,
        )
        with patch("urllib.request.urlopen", side_effect=capture):
            findings = reviewer.review(diff, parsed)
        self.assertEqual(321, captured["max_tokens"])
        self.assertLess(len(captured["messages"][1]["content"]), len(diff))
        self.assertEqual(1, len(findings))
        self.assertEqual((target.path, target.line), (findings[0].path, findings[0].line))
        context = reviewer.evaluation_context()
        self.assertTrue(context["compressed"])
        self.assertEqual(321, context["max_output_tokens"])
        self.assertNotIn("text", context)

    def test_harness_records_safe_context_metadata_without_diff_or_labels_in_prompt(self):
        case = generate_controlled_pr_cases()[0]
        case["scoring"] = {"scope": "target-cwe", "target_cwes": ["CWE-999"]}
        captured = {}

        def capture(request, **_kwargs):
            captured.update(json.loads(request.data.decode("utf-8")))
            return FakeResponse({
                "choices": [{"message": {"content": '{"findings": []}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            })

        reviewer = OpenAICompatibleReviewer(
            "https://example.test", "key", "model",
            context_manager=ContextManager(max_tokens=512, reserved_tokens=64),
            max_output_tokens=100,
            input_cost_per_million=1.0, output_cost_per_million=1.0,
        )
        with patch("urllib.request.urlopen", side_effect=capture):
            result = EndToEndEvaluationHarness().run_case(reviewer, case)
        rendered_prompt = json.dumps(captured["messages"])
        self.assertNotIn("CWE-999", rendered_prompt)
        self.assertEqual("available", result["context"]["status"])
        self.assertNotIn("text", result["context"])
        self.assertNotIn(case["diff"], json.dumps(result))

    def test_invalid_json_gets_one_bounded_compact_repair_attempt(self):
        diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+safe = True\n"
        bodies = [
            {
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": '{"findings": ['},
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
            {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": '{"findings": []}'},
                }],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            },
        ]
        payloads = []

        def capture(request, **_kwargs):
            payloads.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse(bodies[len(payloads) - 1])

        reviewer = OpenAICompatibleReviewer(
            "https://example.test", "key", "model",
            max_output_tokens=100, max_json_repair_attempts=1,
            input_cost_per_million=1.0, output_cost_per_million=1.0,
        )
        with patch("urllib.request.urlopen", side_effect=capture):
            findings = reviewer.review(diff, parse_unified_diff(diff))
        self.assertEqual([], findings)
        self.assertEqual(2, len(payloads))
        self.assertIn("invalid or truncated", payloads[1]["messages"][-1]["content"])
        self.assertEqual(2, reviewer.evaluation_usage()["model_calls"])

    def test_empty_truncated_response_is_not_retried(self):
        diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+safe = True\n"
        body = {
            "choices": [{"finish_reason": "length", "message": {"content": ""}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 100, "total_tokens": 110},
        }
        reviewer = OpenAICompatibleReviewer(
            "https://example.test", "key", "model",
            max_output_tokens=100, max_json_repair_attempts=1,
            input_cost_per_million=1.0, output_cost_per_million=1.0,
        )
        with patch("urllib.request.urlopen", return_value=FakeResponse(body)) as request:
            with self.assertRaisesRegex(RuntimeError, "finish_reason=length"):
                reviewer.review(diff, parse_unified_diff(diff))
        self.assertEqual(1, request.call_count)

    def test_target_cwe_scope_audits_filtered_cwe_ids(self):
        case = generate_controlled_pr_cases()[0]
        case["scoring"] = {"scope": "target-cwe", "target_cwes": ["CWE-999"]}
        line = parse_unified_diff(case["diff"]).added_lines[0]
        body = {
            "choices": [{"message": {"content": json.dumps({"findings": [{
                "rule_id": "CWE-20", "severity": "high", "title": "Validation",
                "explanation": "Validation is missing.", "path": line.path,
                "line": line.line, "evidence": line.content, "fix": "Validate input.",
                "test": "Add a boundary test.", "confidence": 0.8,
            }]})}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        reviewer = OpenAICompatibleReviewer(
            "https://example.test", "key", "model",
            input_cost_per_million=1.0, output_cost_per_million=1.0,
        )
        with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
            result = EndToEndEvaluationHarness().run_case(reviewer, case)
        self.assertEqual(1, result["ignored_out_of_scope_findings"])
        self.assertEqual(["CWE-20"], result["ignored_out_of_scope_cwes"])

    def test_policy_blocks_expensive_routing_candidate(self):
        baseline = {
            "score": 0.8, "precision": 0.8, "recall": 0.8,
            "resource_usage": {
                "usage_status": "available", "latency_ms_p95": 100,
                "total_tokens": 100, "estimated_cost_usd": 0.01,
            },
        }
        candidate = {
            "score": 0.82, "precision": 0.82, "recall": 0.82,
            "resource_usage": {
                "usage_status": "available", "latency_ms_p95": 110,
                "total_tokens": 130, "estimated_cost_usd": 0.011,
            },
        }
        policy = EvaluationPolicy(
            minimum_quality_improvement=0.01,
            maximum_latency_growth_ratio=0.2,
            maximum_token_growth_ratio=0.2,
            maximum_cost_growth_ratio=0.2,
        )
        result = RoutingPolicyEvaluator(policy).evaluate(
            baseline, candidate, require_improvement=True
        )
        self.assertEqual("rejected", result["decision"])
        self.assertFalse(result["gates"]["total_tokens"]["passed"])

    def test_release_provenance_accepts_valid_benchmark_source(self):
        metrics = {
            "precision": 1.0, "recall": 1.0, "f1": 1.0,
            "severity_accuracy": 1.0, "high_risk_recall": 1.0,
            "clean_accuracy": 1.0, "execution_success_rate": 1.0,
            "safe_fix_rate": 1.0, "e2e_security_fix_rate": 1.0,
            "resource_usage": {
                "usage_status": "available", "latency_ms_p95": 1,
                "total_tokens": 1, "estimated_cost_usd": 0.0001,
            },
        }
        report = {
            "name": "benchmark", "dataset": {
                "sha256": "a" * 64, "source_kinds": ["benchmark-derived"],
                "integrity": {"valid": True, "errors": []},
            },
            "metrics": metrics,
            "by_split": {"validation": {"f1": 1.0}, "holdout": {"f1": 1.0}},
        }
        result = comparison_summary(report, report, minimum_f1_improvement=0.0)
        provenance = result["release_gate"]["gates"]["production_data_provenance"]
        self.assertTrue(provenance["passed"])
        self.assertIn("benchmark-derived", provenance["allowed_source_kinds"])


if __name__ == "__main__":
    unittest.main()
