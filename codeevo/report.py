from typing import Any, Dict


def to_markdown(report: Dict[str, Any]) -> str:
    title = "# CodeEvo PR Review"
    if report.get("pull_request") is not None:
        title += " — #%s" % report["pull_request"]
    lines = [
        title,
        "",
        "**Repository:** `%s`  " % report.get("repository", ""),
        "**Risk:** `%s`  " % report.get("risk", "unknown"),
        "**Reviewer:** `%s`" % report.get("reviewer", "unknown"),
        "",
        report.get("summary", ""),
        "",
    ]
    collaboration = report.get("collaboration") or {}
    if collaboration:
        repository_context = collaboration.get("repository_context") or {}
        lines.extend([
            "## Multi-agent collaboration",
            "",
            "- Protocol: `%s`" % collaboration.get("protocol", "unknown"),
            "- Assignments: `%s`; dialogue rounds: `%s`; messages: `%s`" % (
                collaboration.get("planned_assignments", 0),
                collaboration.get("dialogue_rounds", 0),
                collaboration.get("messages", 0),
            ),
            "- Retries: `%s`; handoffs: `%s`; rejected by verification: `%s`" % (
                collaboration.get("retries", 0), collaboration.get("handoffs", 0),
                collaboration.get("rejected_findings", 0),
            ),
            "- Repository context: `%s`; evidence-bound findings: `%s`; "
            "evidence-gate rejections: `%s`" % (
                (
                    "available" if repository_context.get("available")
                    else "required-but-unavailable" if repository_context.get("required")
                    else "disabled"
                ),
                repository_context.get("evidence_bound_findings", 0),
                repository_context.get("evidence_rejections", 0),
            ),
            "",
        ])
    findings = report.get("findings", [])
    if not findings:
        lines.append("✅ No actionable issue detected in the added lines.")
        return "\n".join(lines) + "\n"
    lines.extend(["## Findings", ""])
    icons = {"critical": "🚨", "high": "🔴", "medium": "🟠", "low": "🟡"}
    for index, item in enumerate(findings, 1):
        severity = item.get("severity", "medium")
        lines.extend(
            [
                "### %d. %s %s" % (index, icons.get(severity, "•"), item.get("title", "Finding")),
                "",
                "`%s:%s` · **%s** · `%s`" % (
                    item.get("path", ""), item.get("line", 0), severity.upper(), item.get("rule_id", "")),
                "",
                item.get("explanation", ""),
                "",
                "**Evidence**",
                "",
                "```text",
                item.get("evidence", ""),
                "```",
                "",
                "**Suggested fix:** %s" % item.get("fix", ""),
                "",
                "**Suggested test:** %s" % item.get("test", ""),
                "",
            ]
        )
        references = item.get("context_evidence") or []
        if references:
            lines.extend(["**Repository evidence**", ""])
            for reference in references:
                lines.append(
                    "- `%s` · `%s:%s-%s` · SHA-256 `%s`"
                    % (
                        reference.get("evidence_id", ""),
                        reference.get("path", ""),
                        reference.get("start_line", 0),
                        reference.get("end_line", 0),
                        reference.get("sha256", ""),
                    )
                )
                if reference.get("excerpt"):
                    lines.extend([
                        "", "```text", reference["excerpt"], "```", "",
                    ])
    return "\n".join(lines) + "\n"
