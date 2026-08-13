"""Reproduce the shared offline gate used before a routing policy enters shadow."""
import argparse
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from codeevo.evaluation_policy import EvaluationPolicy  # noqa: E402
from codeevo.rollout import RoutingPolicyEvaluator  # noqa: E402


def fixture():
    baseline = {
        "score": 0.80, "precision": 0.82, "recall": 0.78,
        "high_severity_recall": 0.90, "success_rate": 1.0,
        "positive_cases": 20, "clean_cases": 20,
        "resource_usage": {
            "usage_status": "available", "latency_ms_p95": 800.0,
            "total_tokens": 100000, "estimated_cost_usd": 0.25,
        },
    }
    candidate = {
        "score": 0.83, "precision": 0.84, "recall": 0.82,
        "high_severity_recall": 0.92, "success_rate": 1.0,
        "positive_cases": 20, "clean_cases": 20,
        "resource_usage": {
            "usage_status": "available", "latency_ms_p95": 920.0,
            "total_tokens": 112000, "estimated_cost_usd": 0.28,
        },
    }
    return baseline, candidate


def markdown(result):
    lines = [
        "# CodeEvo 路由策略离线门禁",
        "",
        "决策：**%s**" % result["decision"],
        "",
        "| 门禁 | 结果 | 基线 | 候选 |",
        "|---|---|---:|---:|",
    ]
    for name, gate in result["gates"].items():
        lines.append(
            "| `%s` | %s | %s | %s |" % (
                name, "PASS" if gate["passed"] else "FAIL",
                gate.get("baseline", "—"), gate.get("candidate", "—"),
            )
        )
    lines.extend([
        "",
        "只有通过该离线质量、P95 延迟、Token 和成本门禁的候选才有资格进入 Shadow；"
        "Shadow 通过后再进入 Canary，线上错误预算仍可自动回滚。",
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", default=os.path.join(ROOT, "output", "routing-policy-evaluation")
    )
    args = parser.parse_args()
    baseline, candidate = fixture()
    policy = EvaluationPolicy(
        minimum_quality_improvement=0.01,
        maximum_latency_growth_ratio=0.20,
        maximum_token_growth_ratio=0.20,
        maximum_cost_growth_ratio=0.20,
    )
    result = RoutingPolicyEvaluator(policy).evaluate(
        baseline, candidate, require_improvement=True
    )
    report = {
        "schema_version": 1, "baseline": baseline, "candidate": candidate,
        "evaluation": result,
    }
    os.makedirs(args.output_dir, exist_ok=True)
    json_path = os.path.join(args.output_dir, "routing-policy-report.json")
    markdown_path = os.path.join(args.output_dir, "routing-policy-report.md")
    with open(json_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    with open(markdown_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown(result))
    print("decision:", result["decision"])
    print("report:", json_path)


if __name__ == "__main__":
    main()
