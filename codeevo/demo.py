"""Deterministic, isolated showcase data for the public read-only experience."""
from typing import Any, Dict

from .models import Finding, ReviewReport, Severity, TaskState, TraceEvent
from .store import utc_now


BENCHMARK_SNAPSHOT: Dict[str, Any] = {
    "dataset": "Vul4J benchmark-derived validation subset",
    "cases": 8,
    "repositories": 4,
    "model": "deepseek-chat",
    "prompt_version": "codeevo-benchmark-review-v3",
    "holdout_used": False,
    "routes": [
        {
            "id": "local-rules", "label": "Local rules", "precision": 0.0,
            "recall": 0.0, "f1": 0.0, "clean_accuracy": 1.0,
            "latency_ms_p95": 0.3071, "total_tokens": 0, "model_calls": 0,
        },
        {
            "id": "single-deepseek", "label": "Single DeepSeek", "precision": 0.5,
            "recall": 0.5, "f1": 0.5, "clean_accuracy": 0.75,
            "latency_ms_p95": 8364.3896, "total_tokens": 14671, "model_calls": 8,
        },
        {
            "id": "multi-agent", "label": "Multi-agent", "precision": 1.0,
            "recall": 0.25, "f1": 0.4, "clean_accuracy": 1.0,
            "latency_ms_p95": 49129.3794, "total_tokens": 54281, "model_calls": 25,
        },
    ],
    "disclosure": (
        "这是已发布 Validation 的可复现快照，不会在访客浏览时重新调用付费模型。"
    ),
}


def _finding(
    rule_id: str, severity: Severity, title: str, path: str, line: int,
    evidence: str, explanation: str, fix: str, test: str, confidence: float,
) -> Finding:
    return Finding(
        rule_id=rule_id, severity=severity, title=title, explanation=explanation,
        path=path, line=line, evidence=evidence, fix=fix, test=test,
        confidence=confidence,
    )


SHOWCASE_TASKS = (
    {
        "id": "showcase-multi-agent-payment",
        "repository": "codeevo/payment-service",
        "pull_request": 184,
        "input": {
            "source": "benchmark-replay", "route": "multi-agent",
            "model": "deepseek-chat", "latency_ms": 49129,
            "total_tokens": 54281, "model_calls": 25,
            "dataset": "Vul4J validation snapshot", "demo": True,
        },
        "findings": (
            _finding(
                "SEC-SUBPROCESS-SHELL", Severity.HIGH, "Shell command injection",
                "payments/settlement.py", 48, "subprocess.run(command, shell=True)",
                "An untrusted settlement reference reaches a shell-enabled process.",
                "Pass a fixed argument list and keep shell execution disabled.",
                "Use a reference containing shell metacharacters and assert no extra process starts.",
                0.94,
            ),
            _finding(
                "SEC-HARDCODED-SECRET", Severity.HIGH, "Hard-coded production credential",
                "payments/config.py", 17, 'api_key = "prod_demo_secret"',
                "The added line embeds a credential in source control and build artifacts.",
                "Load the credential from the deployment secret provider.",
                "Fail startup when the secret is absent and scan the repository history.",
                0.91,
            ),
            _finding(
                "REL-DEBUG-PRINT", Severity.LOW, "Sensitive debug output",
                "payments/settlement.py", 52, "print(payment_payload)",
                "The full payment payload can be written to application logs.",
                "Use structured logging with an explicit field allowlist.",
                "Capture logs and assert card and token fields never appear.",
                0.86,
            ),
        ),
        "summary": (
            "Security、Reliability 与 LLM Specialist 并行审查后，Verifier 保留 3 个可复核结论。"
        ),
        "risk": "high",
        "roles": [
            ("planner-agent", "security-review", "assignment", {
                "objective": "检查支付链路的注入、凭据和日志风险", "files": 2,
            }),
            ("context-manager", "security-review", "context_window_prepared", {
                "input_tokens": 1168, "reserved_tokens": 256, "truncated": False,
            }),
            ("agent-runtime", "security-review", "tool_called", {
                "tool": "changed_line", "arguments": {"path": "payments/settlement.py", "line": 48},
            }),
            ("security-review", "critic-agent", "candidate_finding", {
                "rule_id": "SEC-SUBPROCESS-SHELL", "confidence": 0.9,
            }),
            ("critic-agent", "security-review", "critique", {
                "accepted": True, "questions": ["调用参数是否由外部请求控制？"],
            }),
            ("evidence-agent", "verifier-agent", "evidence_result", {
                "reproducible": True, "evidence_id": "sha256:8f4a/payment-settlement-L48",
            }),
            ("verifier-agent", "arbiter-agent", "verification_decision", {
                "approved": True, "confidence": 0.94,
            }),
            ("arbiter-agent", "review-report", "arbitration_decision", {
                "approved_findings": [
                    "SEC-SUBPROCESS-SHELL", "SEC-HARDCODED-SECRET", "REL-DEBUG-PRINT"
                ], "rejected_findings": ["SEC-SQL-CONCAT"],
            }),
        ],
    },
    {
        "id": "showcase-single-agent-auth",
        "repository": "codeevo/identity-api",
        "pull_request": 72,
        "input": {
            "source": "benchmark-replay", "route": "single-deepseek",
            "model": "deepseek-chat", "latency_ms": 8364,
            "total_tokens": 14671, "model_calls": 8,
            "dataset": "Vul4J validation snapshot", "demo": True,
        },
        "findings": (
            _finding(
                "SEC-EVAL", Severity.CRITICAL, "Dynamic code execution",
                "identity/policy.py", 31, "return eval(policy)",
                "A stored policy string is evaluated as Python code.",
                "Replace dynamic evaluation with a typed policy parser.",
                "Submit a policy containing an import expression and verify it is rejected.",
                0.89,
            ),
        ),
        "summary": "单 Agent 路线识别出动态执行风险，并通过新增行位置校验。",
        "risk": "high",
        "roles": [
            ("context-manager", "llm-review", "context_window_prepared", {
                "input_tokens": 1042, "reserved_tokens": 256, "truncated": False,
            }),
            ("agent-runtime", "llm-review", "tool_called", {
                "tool": "search_diff", "arguments": {"query": "eval("},
            }),
            ("llm-review", "verifier-agent", "candidate_finding", {
                "rule_id": "SEC-EVAL", "confidence": 0.89,
            }),
            ("verifier-agent", "review-report", "verification_decision", {
                "approved": True, "confidence": 0.89,
            }),
        ],
    },
    {
        "id": "showcase-local-clean",
        "repository": "codeevo/catalog-service",
        "pull_request": 39,
        "input": {
            "source": "deterministic-replay", "route": "local-rules",
            "model": "none", "latency_ms": 1, "total_tokens": 0,
            "model_calls": 0, "dataset": "public demo fixture", "demo": True,
        },
        "findings": (),
        "summary": "确定性规则完成新增行检查，未发现当前规则集覆盖的风险。",
        "risk": "low",
        "roles": [
            ("planner-agent", "security-review", "assignment", {
                "objective": "执行本地确定性新增行检查", "files": 1,
            }),
            ("security-review", "review-report", "verification_decision", {
                "approved": True, "findings": 0,
            }),
        ],
    },
)


def seed_public_showcase(store, tenant_id: str) -> int:
    """Idempotently create safe showcase tasks inside the guest-only tenant."""
    created = 0
    for spec in SHOWCASE_TASKS:
        if store.get(spec["id"], tenant_id):
            continue
        store.create(
            spec["id"], spec["repository"], spec["pull_request"],
            dict(spec["input"]), tenant_id,
        )
        transitions = (
            (TaskState.PLANNING, "输入已验证，Planner 正在拆解风险域"),
            (TaskState.EXECUTING, "Specialist 正在执行有界工具调用"),
            (TaskState.REVIEWING, "Verifier 与 Arbiter 正在执行证据门禁"),
        )
        for step, (state, message) in enumerate(transitions, 1):
            store.transition(spec["id"], TraceEvent(step, state, message, utc_now()))
        for index, (sender, recipient, kind, content) in enumerate(spec["roles"], 1):
            store.record_agent_message(spec["id"], {
                "sender": sender, "recipient": recipient, "kind": kind,
                "correlation_id": "showcase-%02d" % index, "content": content,
            })
        report = ReviewReport(
            repository=spec["repository"], pull_request=spec["pull_request"],
            summary=spec["summary"], risk=spec["risk"],
            findings=list(spec["findings"]),
            files_reviewed=sorted({item.path for item in spec["findings"]}) or ["catalog/item.py"],
            reviewer=spec["input"]["route"],
            collaboration={
                "protocol": "plan-challenge-revise-evidence-verify-arbitrate",
                "roles": sorted({item[0] for item in spec["roles"]}),
                "messages": len(spec["roles"]),
                "approved_findings": len(spec["findings"]),
                "rejected_findings": 1 if spec["input"]["route"] == "multi-agent" else 0,
            },
        )
        store.succeed(
            spec["id"], report,
            TraceEvent(4, TaskState.SUCCESS, "审查完成，报告已通过质量门禁", utc_now()),
        )
        created += 1
    return created
