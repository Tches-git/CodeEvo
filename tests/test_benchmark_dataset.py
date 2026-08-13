import copy
import unittest
from unittest.mock import patch

from codeevo.benchmark_dataset import build_vul4j_case_pair, reverse_unified_diff
from codeevo.evaluation_dataset import DatasetManifest, validate_dataset_integrity
from codeevo.evaluation_harness import EndToEndEvaluationHarness, validate_case
from codeevo.models import Finding, Severity
from codeevo.reviewer import Reviewer


FORWARD_DIFF = """diff --git a/src/main/java/App.java b/src/main/java/App.java
index aaaaaaa..bbbbbbb 100644
--- a/src/main/java/App.java
+++ b/src/main/java/App.java
@@ -10,3 +10,3 @@ class App {
-    void parse(String value) { eval(value); }
+    void parse(String value) { safeParse(value); }
 }
diff --git a/src/test/java/AppTest.java b/src/test/java/AppTest.java
index ccccccc..ddddddd 100644
--- a/src/test/java/AppTest.java
+++ b/src/test/java/AppTest.java
@@ -1 +1 @@
-assertFails(bad);
+assertSafe(bad);
"""


class BenchmarkDatasetTests(unittest.TestCase):
    def test_reverse_diff_makes_vulnerable_code_an_added_line(self):
        reverse = reverse_unified_diff(FORWARD_DIFF)
        self.assertIn("@@ -10,3 +10,3 @@", reverse)
        self.assertIn("+    void parse(String value) { eval(value); }", reverse)
        self.assertIn("--- a/src/main/java/App.java", reverse)
        self.assertIn("+++ b/src/main/java/App.java", reverse)

    @patch("codeevo.benchmark_dataset.fetch_nvd_severity")
    @patch("codeevo.benchmark_dataset._metadata_with_repository")
    def test_vul4j_pair_is_auditable_and_needs_no_reviewer(self, metadata, severity):
        metadata.return_value = ({
            "sha": "b" * 40,
            "parents": [{"sha": "a" * 40}],
            "repository": {"private": False, "default_branch": "main"},
            "repository_license": {
                "html_url": "https://github.com/org/repo/blob/main/LICENSE",
                "license": {"spdx_id": "Apache-2.0"},
            },
        }, FORWARD_DIFF, "https://api.github.com/repos/org/repo/commits/" + "b" * 40)
        severity.return_value = (
            "high", "CVSS:3.1/AV:N/AC:L", "https://nvd.nist.gov/vuln/detail/CVE-2024-0001"
        )
        row = {
            "vul_id": "VUL4J-X", "cve_id": "CVE-2024-0001", "cwe_id": "CWE-95",
            "human_patch": "https://github.com/org/repo/commit/" + "b" * 40,
            "failing_tests": "AppTest#bad",
        }
        risk, clean = build_vul4j_case_pair(row, "test", "salt")
        validate_case(risk)
        validate_case(clean)
        self.assertEqual(0, risk["annotation"]["reviewer_count"])
        self.assertEqual("benchmark-derived", risk["source"]["kind"])
        self.assertEqual("reverse", risk["source"]["derivation"]["patch_operation"])
        self.assertEqual("forward", clean["source"]["derivation"]["patch_operation"])
        self.assertEqual([], clean["expected_findings"])
        self.assertEqual(1, len(risk["expected_findings"]))
        self.assertEqual("src/main/java/App.java", risk["expected_findings"][0]["path"])
        manifest, integrity = DatasetManifest.from_cases(
            [risk, clean], "vul4j", "test", require_benchmark_provenance=True
        )
        self.assertTrue(integrity["valid"])
        self.assertEqual(["benchmark-derived"], manifest.source_kinds)

        forged = copy.deepcopy(risk)
        forged["source"]["verification"]["status"] = "claimed"
        result = validate_dataset_integrity([forged], require_benchmark_provenance=True)
        self.assertFalse(result["valid"])
        self.assertTrue(any("status is not trusted" in item for item in result["errors"]))

        tampered = copy.deepcopy(risk)
        tampered["source"]["benchmark"]["record"]["cwe_id"] = "CWE-22"
        result = validate_dataset_integrity([tampered], require_benchmark_provenance=True)
        self.assertFalse(result["valid"])
        self.assertTrue(any("does not match record" in item for item in result["errors"]))

    def test_target_cwe_scoring_ignores_unrelated_findings_and_location(self):
        class TargetReviewer(Reviewer):
            name = "target-reviewer"

            def review(self, _diff, _parsed):
                return [
                    Finding(
                        "CWE-95", Severity.HIGH, "target", "", "elsewhere.java", 999,
                        "", "", "",
                    ),
                    Finding(
                        "CWE-22", Severity.HIGH, "unrelated", "", "App.java", 10,
                        "", "", "",
                    ),
                ]

        case = {
            "schema_version": 2, "id": "target-case", "repository": "org/repo",
            "pull_request": 0, "split": "validation", "diff": FORWARD_DIFF,
            "scoring": {"scope": "target-cwe", "target_cwes": ["CWE-95"]},
            "expected_findings": [{
                "path": "src/main/java/App.java", "start_line": 10, "end_line": 10,
                "cwe": "CWE-95", "severity": "high",
            }],
        }
        validate_case(case)
        result = EndToEndEvaluationHarness().run(TargetReviewer(), [case])
        self.assertEqual(1, result["metrics"]["tp"])
        self.assertEqual(0, result["metrics"]["fp"])
        self.assertEqual(1, result["case_results"][0]["ignored_out_of_scope_findings"])


if __name__ == "__main__":
    unittest.main()
