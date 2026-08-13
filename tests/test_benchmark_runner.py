import json
import tempfile
import unittest
from pathlib import Path

from codeevo.benchmark_runner import (
    BenchmarkRunner,
    CweDeduplicatingReviewer,
    RouteDefinition,
    main,
    normalize_routes,
    render_html,
)
from codeevo.evaluation_benchmark import generate_controlled_pr_cases
from codeevo.evaluation_harness import EndToEndEvaluationHarness
from codeevo.reviewer import LocalRuleReviewer, Reviewer
from codeevo.models import Finding, Severity


class CountingReviewer(Reviewer):
    def __init__(self, name):
        self.name = name
        self.calls = 0
        self.delegate = LocalRuleReviewer()

    def review(self, diff, parsed):
        self.calls += 1
        return self.delegate.review(diff, parsed)


class BenchmarkRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dataset = self.root / "cases.jsonl"
        cases = generate_controlled_pr_cases()[:8]
        with self.dataset.open("w", encoding="utf-8") as handle:
            for case in cases:
                handle.write(json.dumps(case, ensure_ascii=False) + "\n")

    def tearDown(self):
        self.temporary.cleanup()

    def test_routes_share_dataset_and_resume_without_review_calls(self):
        reviewers = {
            "local-rules": CountingReviewer("fake-local"),
            "single-deepseek": CountingReviewer("fake-single"),
            "multi-agent": CountingReviewer("fake-multi"),
        }
        factories = {name: (lambda item=item: item) for name, item in reviewers.items()}
        output = self.root / "output"
        first = BenchmarkRunner(
            str(self.dataset), str(output), ["local,single,multi"],
            splits=("validation",), limit=4, route_overrides=factories,
        ).run()
        hashes = {route["dataset"]["sha256"] for route in first["routes"].values()}
        self.assertEqual(1, len(hashes))
        self.assertEqual(["local-rules", "single-deepseek", "multi-agent"], list(first["routes"]))
        self.assertTrue(all(item.calls == 4 for item in reviewers.values()))
        self.assertTrue((output / "benchmark-report.json").is_file())
        self.assertTrue((output / "benchmark-report.md").is_file())
        self.assertTrue((output / "benchmark-report.html").is_file())

        second = BenchmarkRunner(
            str(self.dataset), str(output), ["local,single,multi"],
            splits=("validation",), resume=True, limit=4,
            route_overrides=factories,
        ).run()
        self.assertTrue(all(item.calls == 4 for item in reviewers.values()))
        self.assertEqual(
            {"executed": 0, "reused": 4},
            second["experiment"]["checkpoint_stats"]["single-deepseek"],
        )
        self.assertEqual(
            first["routes"]["local-rules"]["metrics"],
            second["routes"]["local-rules"]["metrics"],
        )

    def test_dimensions_and_failure_taxonomy_are_reported(self):
        class BrokenReviewer(Reviewer):
            name = "broken"

            def review(self, diff, parsed):
                raise TimeoutError("simulated timeout")

        report = BenchmarkRunner(
            str(self.dataset), str(self.root / "failure"), ["single"],
            splits=("validation",), limit=1,
            route_overrides={"single-deepseek": BrokenReviewer},
        ).run()
        self.assertEqual("TimeoutError", report["failures"][0]["error_type"])
        dimensions = report["dimensions"]["single-deepseek"]
        self.assertIn("validation", dimensions["by_split"])
        self.assertIn("acme/service-01", dimensions["by_repository"])
        self.assertIn("CWE-95", dimensions["by_cwe"])
        self.assertIn("critical", dimensions["by_severity"])

    def test_non_cwe_rule_ids_do_not_pollute_cwe_dimension(self):
        class ReliabilityReviewer(Reviewer):
            name = "reliability"

            def review(self, diff, parsed):
                line = parsed.added_lines[0]
                return [Finding(
                    "RETURN-VALUE-REGRESSION", Severity.MEDIUM,
                    "return regression", "Return behavior changed unexpectedly.",
                    line.path, line.line, line.content.strip(),
                    "Return the normalized value.", "Add a return-value test.", 0.9,
                )]

        report = BenchmarkRunner(
            str(self.dataset), str(self.root / "non-cwe"), ["single"],
            splits=("validation",), limit=1,
            route_overrides={"single-deepseek": ReliabilityReviewer},
        ).run()
        cwes = report["dimensions"]["single-deepseek"]["by_cwe"]
        self.assertNotIn("RETURN-VALUE-REGRESSION", cwes)

    def test_html_escapes_untrusted_report_values(self):
        reviewer = CountingReviewer("local")
        report = BenchmarkRunner(
            str(self.dataset), str(self.root / "escaped"), ["local"],
            splits=("validation",), limit=1,
            route_overrides={"local-rules": lambda: reviewer},
        ).run()
        report["dataset"]["path"] = "<script>alert(1)</script>"
        rendered = render_html(report)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_holdout_requires_explicit_confirmation(self):
        code = main([
            "--dataset", str(self.dataset),
            "--output-dir", str(self.root / "holdout"),
            "--routes", "local", "--splits", "holdout",
        ])
        self.assertEqual(2, code)

    def test_harness_can_summarize_checkpoint_results(self):
        cases = generate_controlled_pr_cases()[:2]
        reviewer = LocalRuleReviewer()
        harness = EndToEndEvaluationHarness()
        results = [harness.run_case(reviewer, case) for case in cases]
        summary = harness.summarize(reviewer, cases, results)
        self.assertEqual(2, summary["metrics"]["cases"])
        with self.assertRaises(ValueError):
            harness.summarize(reviewer, cases, list(reversed(results)))

    def test_route_aliases_are_deduplicated(self):
        self.assertEqual(
            ["local-rules", "single-deepseek", "multi-agent"],
            normalize_routes(["multi,local,single,local-rules"]),
        )

    def test_multi_route_collapses_equivalent_rule_and_cwe_ids(self):
        class DuplicateReviewer(Reviewer):
            name = "duplicate"

            def review(self, diff, parsed):
                line = parsed.added_lines[0]
                values = []
                for rule, confidence in (("SEC-EVAL", 0.9), ("CWE-95", 0.95)):
                    values.append(Finding(
                        rule, Severity.CRITICAL, "dynamic execution",
                        "Untrusted input can execute code.", line.path, line.line,
                        line.content.strip(), "Use a strict parser.",
                        "Add a malicious expression test.", confidence,
                    ))
                return values

        case = generate_controlled_pr_cases()[0]
        from codeevo.diff_parser import parse_unified_diff
        findings = CweDeduplicatingReviewer(DuplicateReviewer()).review(
            case["diff"], parse_unified_diff(case["diff"])
        )
        self.assertEqual(1, len(findings))
        self.assertEqual("CWE-95", findings[0].rule_id)

    def test_budget_config_changes_checkpoint_identity(self):
        case = generate_controlled_pr_cases()[0]
        first = RouteDefinition(
            "single-deepseek", LocalRuleReviewer(), "deepseek", "model", "prompt",
            ["reviewer"], "config-a", {"max_output_tokens": 1200},
        )
        second = RouteDefinition(
            "single-deepseek", LocalRuleReviewer(), "deepseek", "model", "prompt",
            ["reviewer"], "config-b", {"max_output_tokens": 600},
        )
        key_a = BenchmarkRunner._checkpoint_key("dataset", first, case)
        key_b = BenchmarkRunner._checkpoint_key("dataset", second, case)
        self.assertNotEqual(key_a, key_b)

    def test_deduplicating_wrapper_forwards_context_metadata(self):
        class ContextReviewer(Reviewer):
            name = "context"

            def review(self, diff, parsed):
                return []

            def evaluation_context(self):
                return {"status": "available", "compressed": True}

        context = CweDeduplicatingReviewer(ContextReviewer()).evaluation_context()
        self.assertTrue(context["compressed"])


if __name__ == "__main__":
    unittest.main()
