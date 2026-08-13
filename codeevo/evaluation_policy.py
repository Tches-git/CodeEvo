"""Shared quality, latency, token and cost gates for agent evolution."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional, Sequence


COUNTER_FIELDS = (
    "input_tokens", "output_tokens", "total_tokens", "model_calls",
)


def read_evaluation_usage(reviewer: object) -> Dict[str, Any]:
    """Read a cumulative usage snapshot without inventing unavailable values."""
    provider = getattr(reviewer, "evaluation_usage", None)
    if not callable(provider):
        return {
            "usage_status": "unavailable", "token_status": "unavailable",
            "cost_status": "unavailable", "input_tokens": None,
            "output_tokens": None, "total_tokens": None, "model_calls": None,
            "estimated_cost_usd": None,
        }
    try:
        value = dict(provider() or {})
    except Exception:
        value = {}
    status = str(value.get("usage_status", "unavailable"))
    result = {
        "usage_status": status,
        "token_status": str(value.get("token_status", status)),
        "cost_status": str(value.get("cost_status", status)),
        "estimated_cost_usd": value.get("estimated_cost_usd"),
    }
    for field in COUNTER_FIELDS:
        result[field] = value.get(field)
    for field in (
        "responses", "responses_with_token_usage", "responses_with_cost",
    ):
        if field in value:
            result[field] = value[field]
    return result


def usage_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Return one-case usage from two cumulative snapshots."""
    before_status = str(before.get("usage_status", "unavailable"))
    after_status = str(after.get("usage_status", "unavailable"))
    if before_status == "not_applicable" and after_status == "not_applicable":
        return {
            "usage_status": "not_applicable", "token_status": "not_applicable",
            "cost_status": "not_applicable", "input_tokens": 0,
            "output_tokens": 0, "total_tokens": 0, "model_calls": 0,
            "estimated_cost_usd": 0.0,
        }

    result: Dict[str, Any] = {
        "usage_status": "available" if after_status == "available" else "unavailable",
        "token_status": str(after.get("token_status", "unavailable")),
        "cost_status": str(after.get("cost_status", "unavailable")),
    }
    for field in COUNTER_FIELDS:
        start, end = before.get(field), after.get(field)
        result[field] = max(0, int(end) - int(start)) if start is not None and end is not None else None
    start_cost, end_cost = before.get("estimated_cost_usd"), after.get("estimated_cost_usd")
    result["estimated_cost_usd"] = (
        round(max(0.0, float(end_cost) - float(start_cost)), 10)
        if start_cost is not None and end_cost is not None else None
    )

    # Providers expose observation counters so partial/missing usage objects are visible.
    response_delta = _counter_delta(before, after, "responses")
    token_observation_delta = _counter_delta(
        before, after, "responses_with_token_usage"
    )
    cost_observation_delta = _counter_delta(before, after, "responses_with_cost")
    if response_delta is not None:
        if token_observation_delta != response_delta:
            result["token_status"] = "unavailable"
            for field in ("input_tokens", "output_tokens", "total_tokens"):
                result[field] = None
        if cost_observation_delta != response_delta:
            result["cost_status"] = "unavailable"
            result["estimated_cost_usd"] = None
    if result["token_status"] == "unavailable" and result["cost_status"] == "unavailable":
        result["usage_status"] = "unavailable"
    return result


def _counter_delta(before: dict, after: dict, field: str) -> Optional[int]:
    start, end = before.get(field), after.get(field)
    if start is None or end is None:
        return None
    return max(0, int(end) - int(start))


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize_resources(case_results: Iterable[dict]) -> Dict[str, Any]:
    results = list(case_results)
    latencies = [float(item.get("latency_ms", 0.0)) for item in results]
    usages = [dict(item.get("usage") or {}) for item in results]
    token_available = all(
        usage.get("token_status") in {"available", "not_applicable"}
        for usage in usages
    )
    cost_available = all(
        usage.get("cost_status") in {"available", "not_applicable"}
        for usage in usages
    )
    model_calls_available = all(usage.get("model_calls") is not None for usage in usages)

    def total(field: str, available: bool) -> Optional[int]:
        if not available:
            return None
        return sum(int(usage.get(field) or 0) for usage in usages)

    input_tokens = total("input_tokens", token_available)
    output_tokens = total("output_tokens", token_available)
    total_tokens = total("total_tokens", token_available)
    model_calls = total("model_calls", model_calls_available)
    estimated_cost = (
        round(sum(float(usage.get("estimated_cost_usd") or 0.0) for usage in usages), 10)
        if cost_available else None
    )
    case_count = len(results)
    return {
        "usage_status": (
            "not_applicable"
            if usages and all(item.get("usage_status") == "not_applicable" for item in usages)
            else "available" if token_available and cost_available and model_calls_available
            else "partial" if token_available or cost_available or model_calls_available
            else "unavailable"
        ),
        "token_status": "available" if token_available else "unavailable",
        "cost_status": "available" if cost_available else "unavailable",
        "latency_ms_mean": round(sum(latencies) / case_count, 4) if case_count else 0.0,
        "latency_ms_p50": round(percentile(latencies, 0.50), 4),
        "latency_ms_p95": round(percentile(latencies, 0.95), 4),
        "latency_ms_p99": round(percentile(latencies, 0.99), 4),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "model_calls": model_calls,
        "estimated_cost_usd": estimated_cost,
        "cost_per_case_usd": (
            round(estimated_cost / case_count, 10)
            if estimated_cost is not None and case_count else None
        ),
    }


@dataclass(frozen=True)
class EvaluationPolicy:
    """One release policy shared by prompt, skill and routing candidates."""

    minimum_quality_improvement: float = 0.01
    maximum_quality_regression: float = 0.0
    maximum_latency_growth_ratio: float = 0.25
    maximum_token_growth_ratio: float = 0.20
    maximum_cost_growth_ratio: float = 0.20
    minimum_baseline_latency_ms: float = 1.0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if float(value) < 0:
                raise ValueError("%s cannot be negative" % name)

    def evaluate(
        self, baseline: Dict[str, Any], candidate: Dict[str, Any],
        improvement_metric: str = "score", require_improvement: bool = True,
        protected_quality_metrics: Sequence[str] = (
            "score", "precision", "recall", "high_severity_recall",
            "severity_accuracy", "clean_accuracy", "success_rate",
        ),
    ) -> Dict[str, Any]:
        gates: Dict[str, Dict[str, Any]] = {}
        if require_improvement:
            baseline_value = float(baseline.get(improvement_metric, 0.0))
            candidate_value = float(candidate.get(improvement_metric, 0.0))
            gates["quality_improvement"] = {
                "passed": candidate_value >= baseline_value + self.minimum_quality_improvement,
                "metric": improvement_metric,
                "baseline": baseline_value,
                "candidate": candidate_value,
                "minimum_delta": self.minimum_quality_improvement,
            }

        for metric in protected_quality_metrics:
            if metric not in baseline or metric not in candidate:
                continue
            # Empty positive/clean subsets do not create artificial quality gates.
            if metric == "severity_accuracy" and not baseline.get("positive_cases", 0):
                continue
            if metric == "clean_accuracy" and not baseline.get("clean_cases", 0):
                continue
            baseline_value = float(baseline.get(metric, 0.0))
            candidate_value = float(candidate.get(metric, 0.0))
            gates["%s_non_regression" % metric] = {
                "passed": candidate_value + self.maximum_quality_regression >= baseline_value,
                "baseline": baseline_value, "candidate": candidate_value,
                "maximum_regression": self.maximum_quality_regression,
            }

        baseline_resource = dict(baseline.get("resource_usage") or {})
        candidate_resource = dict(candidate.get("resource_usage") or {})
        gates["latency_p95"] = self._growth_gate(
            baseline_resource.get("latency_ms_p95"),
            candidate_resource.get("latency_ms_p95"),
            self.maximum_latency_growth_ratio,
            minimum_baseline=self.minimum_baseline_latency_ms,
        )
        gates["total_tokens"] = self._growth_gate(
            baseline_resource.get("total_tokens"), candidate_resource.get("total_tokens"),
            self.maximum_token_growth_ratio,
        )
        gates["estimated_cost"] = self._growth_gate(
            baseline_resource.get("estimated_cost_usd"),
            candidate_resource.get("estimated_cost_usd"),
            self.maximum_cost_growth_ratio,
        )
        return {
            "schema_version": 1,
            "passed": all(gate["passed"] for gate in gates.values()),
            "gates": gates,
            "policy": asdict(self),
            "observability": {
                "baseline_usage_status": baseline_resource.get("usage_status", "unavailable"),
                "candidate_usage_status": candidate_resource.get("usage_status", "unavailable"),
                "token_comparison_available": (
                    baseline_resource.get("total_tokens") is not None
                    and candidate_resource.get("total_tokens") is not None
                ),
                "cost_comparison_available": (
                    baseline_resource.get("estimated_cost_usd") is not None
                    and candidate_resource.get("estimated_cost_usd") is not None
                ),
            },
        }

    @staticmethod
    def _growth_gate(
        baseline: Any, candidate: Any, maximum_growth_ratio: float,
        minimum_baseline: float = 0.0,
    ) -> Dict[str, Any]:
        if baseline is None or candidate is None:
            return {
                "passed": True, "status": "unavailable", "baseline": baseline,
                "candidate": candidate, "maximum_growth_ratio": maximum_growth_ratio,
            }
        baseline_value, candidate_value = float(baseline), float(candidate)
        if baseline_value <= minimum_baseline:
            limit = minimum_baseline * (1.0 + maximum_growth_ratio)
            return {
                "passed": candidate_value <= limit,
                "status": "insufficient_baseline" if minimum_baseline else "not_applicable",
                "baseline": baseline_value, "candidate": candidate_value,
                "maximum": limit,
                "maximum_growth_ratio": maximum_growth_ratio,
            }
        limit = baseline_value * (1.0 + maximum_growth_ratio)
        return {
            "passed": candidate_value <= limit,
            "status": "measured", "baseline": baseline_value,
            "candidate": candidate_value, "maximum": limit,
            "maximum_growth_ratio": maximum_growth_ratio,
        }
