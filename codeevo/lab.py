"""Read-only views over published evaluation and evolution artifacts."""
import json
from pathlib import Path
from typing import Any, Dict, Iterable


ARTIFACTS = {
    "evaluation": "output/vul4j-benchmark-0.8-validation-final/benchmark-report.json",
    "evolution": "output/prompt-evolution-proof/prompt-evolution-proof.json",
    "routing": "output/routing-policy-evaluation/routing-policy-report.json",
}


def _roots() -> Iterable[Path]:
    module = Path(__file__).resolve()
    yield Path.cwd()
    yield Path("/app")
    yield module.parent.parent
    for parent in module.parents:
        yield parent


def artifact_path(name: str) -> Path:
    relative = ARTIFACTS[name]
    checked = set()
    for root in _roots():
        candidate = (root / relative).resolve()
        if candidate in checked:
            continue
        checked.add(candidate)
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("published %s artifact is unavailable" % name)


def _read(name: str) -> Dict[str, Any]:
    with artifact_path(name).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("published artifact root must be an object")
    return value


def _route_outcome(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "expected": case.get("expected", 0),
        "predicted": case.get("predicted", 0),
        "tp": case.get("tp", 0),
        "fp": case.get("fp", 0),
        "fn": case.get("fn", 0),
        "clean_hit": bool(case.get("clean_hit")),
        "execution_success": bool(case.get("execution_success")),
        "latency_ms": case.get("latency_ms", 0),
        "target_cwes": list(case.get("target_cwes") or []),
        "expected_findings": list(case.get("expected_findings") or []),
        "predicted_findings": list(case.get("predicted_findings") or []),
        "matches": list(case.get("matches") or []),
        "usage": dict(case.get("usage") or {}),
        "context": dict(case.get("context") or {}),
        "error_type": case.get("error_type"),
    }


def evaluation_lab() -> Dict[str, Any]:
    report = _read("evaluation")
    routes = []
    cases: Dict[str, Dict[str, Any]] = {}
    for route_id, route in (report.get("routes") or {}).items():
        metrics = dict(route.get("metrics") or {})
        resource = dict(metrics.pop("resource_usage", {}) or {})
        routes.append({
            "id": route_id,
            "reviewer": route.get("reviewer", route_id),
            "metrics": metrics,
            "resource_usage": resource,
            "duration_seconds": route.get("duration_seconds", 0),
        })
        for item in route.get("case_results") or []:
            if item.get("split") == "holdout":
                continue
            case_id = str(item.get("id", ""))
            record = cases.setdefault(case_id, {
                "id": case_id,
                "repository": item.get("repository", ""),
                "split": item.get("split", "validation"),
                "kind": "clean" if not item.get("expected") else "risk",
                "target_cwes": list(item.get("target_cwes") or []),
                "routes": {},
            })
            record["routes"][route_id] = _route_outcome(item)
    case_values = sorted(cases.values(), key=lambda item: item["id"])
    failure_counts = {"false_negative": 0, "false_positive": 0, "execution_error": 0}
    for item in case_values:
        for outcome in item["routes"].values():
            failure_counts["false_negative"] += int(outcome["fn"] or 0)
            failure_counts["false_positive"] += int(outcome["fp"] or 0)
            failure_counts["execution_error"] += int(not outcome["execution_success"])
    return {
        "schema_version": report.get("schema_version", 1),
        "experiment": dict(report.get("experiment") or {}),
        "dataset": dict(report.get("dataset") or {}),
        "routes": routes,
        "cases": case_values,
        "failure_counts": failure_counts,
        "filters": {
            "repositories": sorted({item["repository"] for item in case_values}),
            "cwes": sorted({cwe for item in case_values for cwe in item["target_cwes"]}),
            "kinds": ["risk", "clean"],
        },
        "holdout": {
            "used": bool((report.get("experiment") or {}).get("holdout_used")),
            "truth_exposed": False,
        },
    }


def evaluation_case(case_id: str) -> Dict[str, Any]:
    data = evaluation_lab()
    for item in data["cases"]:
        if item["id"] == case_id:
            return {
                "dataset_sha256": data["dataset"].get("sha256", ""),
                "case": item,
                "holdout_truth_exposed": False,
            }
    raise KeyError(case_id)


def _score_summary(value: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "cases", "positive_cases", "clean_cases", "expected_findings",
        "predicted_findings", "precision", "recall", "f1", "score",
        "clean_accuracy", "high_severity_recall", "severity_accuracy",
        "success_rate", "resource_usage",
    )
    return {key: value.get(key) for key in keys if key in value}


def evolution_lab() -> Dict[str, Any]:
    proof = _read("evolution")
    routing = _read("routing")
    dataset = dict(proof.get("dataset") or {})
    dataset.pop("path", None)
    validation = dict(proof.get("validation") or {})
    holdout = dict(proof.get("holdout") or {})
    return {
        "schema_version": proof.get("schema_version", 1),
        "generated_at": proof.get("generated_at"),
        "claim_scope": dict(proof.get("claim_scope") or {}),
        "dataset": dataset,
        "feedback": dict(proof.get("feedback") or {}),
        "evolution_run": dict(proof.get("evolution_run") or {}),
        "validation": {
            "baseline": _score_summary(dict(validation.get("baseline") or {})),
            "candidate": _score_summary(dict(validation.get("candidate") or {})),
            "delta": dict(validation.get("delta") or {}),
        },
        "holdout": {
            "baseline": _score_summary(dict(holdout.get("baseline") or {})),
            "candidate": _score_summary(dict(holdout.get("candidate") or {})),
            "delta": dict(holdout.get("delta") or {}),
            "case_truth_exposed": False,
        },
        "versions": list(proof.get("versions") or []),
        "release_gate": dict(proof.get("release_gate") or {}),
        "routing_policy": routing,
    }
