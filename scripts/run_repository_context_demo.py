"""Run a deterministic repository-context review and write evidence artifacts."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from codeevo.agents import MultiAgentCoordinator  # noqa: E402
from codeevo.diff_parser import parse_unified_diff  # noqa: E402
from codeevo.models import ReviewReport  # noqa: E402
from codeevo.report import to_markdown  # noqa: E402
from codeevo.reviewer import ReliabilityRuleReviewer, SecurityRuleReviewer  # noqa: E402
from codeevo.workspace import RepositoryWorkspaceResolver  # noqa: E402


SOURCE = """def execute_expression(user_input):
    return eval(user_input)

def handle_request(request):
    return execute_expression(request.query["expression"])
"""

DIFF = """--- a/src/service.py
+++ b/src/service.py
@@ -1,5 +1,5 @@
 def execute_expression(user_input):
-    return user_input
+    return eval(user_input)

 def handle_request(request):
     return execute_expression(request.query["expression"])
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the CodeEvo repository-context evidence demo"
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(ROOT, "output", "repository-context-demo"),
    )
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temporary:
        repository = Path(temporary) / "acme" / "payments-api"
        (repository / "src").mkdir(parents=True)
        (repository / "src" / "service.py").write_text(SOURCE, encoding="utf-8")

        resolver = RepositoryWorkspaceResolver(temporary)
        workspace = resolver.resolve("acme/payments-api")
        index = workspace.index.status()
        symbols = workspace.index.find_symbols("execute_expression")
        callers = workspace.index.find_callers("execute_expression")

        coordinator = MultiAgentCoordinator(
            [SecurityRuleReviewer(), ReliabilityRuleReviewer()],
            workspace_resolver=resolver,
        )
        task_id = "repository-context-demo"
        findings = coordinator.review_with_context(
            task_id,
            DIFF,
            parse_unified_diff(DIFF),
            repository="acme/payments-api",
        )
        report = ReviewReport(
            repository="acme/payments-api",
            pull_request=42,
            summary=(
                "Repository-aware review reproduced a critical finding and "
                "bound it to a hashed source read."
            ),
            risk="high",
            findings=findings,
            files_reviewed=["src/service.py"],
            reviewer=coordinator.name,
            collaboration=coordinator.collaboration_summary(task_id),
        ).to_dict()
        artifact = {
            "index": index,
            "symbols": symbols,
            "callers": callers,
            "report": report,
        }

    json_path = output / "repository-context-report.json"
    markdown_path = output / "repository-context-report.md"
    json_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown_path.write_text(to_markdown(report), encoding="utf-8")
    print("json:", json_path)
    print("markdown:", markdown_path)
    print(
        "parser=%s symbols=%d callers=%d findings=%d evidence=%d"
        % (
            index["parser"],
            len(symbols),
            len(callers),
            len(findings),
            sum(len(item.context_evidence) for item in findings),
        )
    )


if __name__ == "__main__":
    main()
