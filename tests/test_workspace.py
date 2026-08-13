import os
import tempfile
import unittest
from pathlib import Path

from codeevo.agents import MultiAgentCoordinator
from codeevo.diff_parser import parse_unified_diff
from codeevo.models import Finding, Severity
from codeevo.reviewer import Reviewer, SecurityRuleReviewer
from codeevo.report import to_markdown
from codeevo.workspace import (
    RepositoryWorkspaceResolver,
    WorkspaceSecurityError,
    WorkspaceSession,
)


SOURCE = """def dangerous(value):
    return eval(value)

def caller(data):
    return dangerous(data)
"""

RISK_DIFF = """--- a/src/app.py
+++ b/src/app.py
@@ -1,5 +1,5 @@
 def dangerous(value):
-    return value
+    return eval(value)

 def caller(data):
     return dangerous(data)
"""


class RepositoryToolAgent(Reviewer):
    name = "repository-tool-agent"
    domains = ("correctness",)

    def review(self, diff, parsed):
        return []

    def agent_step(self, state):
        if not state.get("observations"):
            return {
                "action": "tool",
                "tool": "read_repository_file",
                "arguments": {
                    "path": "src/app.py", "start_line": 1, "end_line": 3,
                },
            }
        return {
            "action": "final",
            "findings": [Finding(
                "CTX-CALL", Severity.MEDIUM, "Unchecked dangerous call",
                "The changed caller invokes the dangerous helper without validation.",
                "src/app.py", 2, "return eval(value)",
                "Validate data before calling the helper.",
                "Add a regression test with rejected input.",
                0.9,
            )],
        }


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.repository = self.base / "org" / "repo"
        (self.repository / "src").mkdir(parents=True)
        (self.repository / "src" / "app.py").write_text(SOURCE, encoding="utf-8")
        (self.repository / ".env").write_text("TOKEN=secret", encoding="utf-8")
        self.resolver = RepositoryWorkspaceResolver(str(self.base))
        self.workspace = self.resolver.resolve("org/repo")

    def tearDown(self):
        self.temporary.cleanup()

    def test_read_scope_rejects_traversal_sensitive_files_and_symlinks(self):
        outside = self.base / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        os.symlink(outside, self.repository / "src" / "escape.txt")

        with self.assertRaises(WorkspaceSecurityError):
            self.workspace.read_file("../outside.txt")
        with self.assertRaises(WorkspaceSecurityError):
            self.workspace.read_file(str(outside))
        with self.assertRaises(WorkspaceSecurityError):
            self.workspace.read_file(".env")
        with self.assertRaises(WorkspaceSecurityError):
            self.workspace.read_file("src/escape.txt")
        self.assertNotIn(".env", self.workspace.list_files())
        self.assertNotIn("src/escape.txt", self.workspace.list_files())

    def test_read_ledger_returns_content_hash_and_line_bound_evidence(self):
        session = WorkspaceSession(self.workspace)

        result = session.read_file("src/app.py", 1, 3)
        evidence = session.evidence_for("src/app.py", 2)

        self.assertEqual(64, len(result["sha256"]))
        self.assertEqual(20, len(result["evidence_id"]))
        self.assertIn("2:     return eval(value)", result["content"])
        self.assertEqual("return eval(value)", evidence[0]["excerpt"].strip())
        with self.assertRaisesRegex(ValueError, "200 lines"):
            session.read_file("src/app.py", 1, 201)

    def test_tree_sitter_finds_symbols_references_and_callers(self):
        status = self.workspace.index.status()
        symbols = self.workspace.index.find_symbols("dangerous")
        references = self.workspace.index.find_references("dangerous")
        callers = self.workspace.index.find_callers("dangerous")

        self.assertEqual("tree-sitter-language-pack", status["parser"])
        self.assertEqual("function", symbols[0]["kind"])
        self.assertEqual(1, symbols[0]["start_line"])
        self.assertEqual([1, 5], [item["line"] for item in references])
        self.assertEqual("caller", callers[0]["caller"])
        self.assertEqual(5, callers[0]["line"])

    def test_high_risk_finding_is_bound_to_repository_evidence(self):
        coordinator = MultiAgentCoordinator(
            [SecurityRuleReviewer()], workspace_resolver=self.resolver
        )
        parsed = parse_unified_diff(RISK_DIFF)

        findings = coordinator.review_with_context(
            "", RISK_DIFF, parsed, repository="org/repo"
        )

        self.assertEqual(1, len(findings))
        self.assertEqual("SEC-EVAL", findings[0].rule_id)
        self.assertEqual("repository", findings[0].context_evidence[0]["source"])
        self.assertEqual(20, len(findings[0].context_evidence[0]["evidence_id"]))
        markdown = to_markdown({
            "repository": "org/repo", "risk": "high", "findings": [
                findings[0].to_dict()
            ],
        })
        self.assertIn("Repository evidence", markdown)
        self.assertIn(findings[0].context_evidence[0]["evidence_id"], markdown)

    def test_high_risk_finding_is_rejected_when_checkout_does_not_match(self):
        mismatch = self.base / "org" / "mismatch" / "src"
        mismatch.mkdir(parents=True)
        (mismatch / "app.py").write_text(
            SOURCE.replace("eval(value)", "value"), encoding="utf-8"
        )
        coordinator = MultiAgentCoordinator(
            [SecurityRuleReviewer()], workspace_resolver=self.resolver
        )

        findings = coordinator.review_with_context(
            "", RISK_DIFF, parse_unified_diff(RISK_DIFF), repository="org/mismatch"
        )

        self.assertEqual([], findings)

    def test_agent_tool_read_is_attached_to_finding(self):
        coordinator = MultiAgentCoordinator(
            [RepositoryToolAgent()], workspace_resolver=self.resolver,
            agent_loop_max_steps=3,
        )

        findings = coordinator.review_with_context(
            "", RISK_DIFF, parse_unified_diff(RISK_DIFF), repository="org/repo"
        )

        self.assertEqual(1, len(findings))
        self.assertEqual("CTX-CALL", findings[0].rule_id)
        self.assertTrue(findings[0].context_evidence)
        self.assertEqual("return eval(value)",
                         findings[0].context_evidence[0]["excerpt"].strip())


if __name__ == "__main__":
    unittest.main()
