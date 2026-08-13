"""Provenance and isolation controls for evaluation datasets."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple


DATASET_MANIFEST_SCHEMA_VERSION = 1
CASE_SCHEMA_VERSION = 2
SPLITS = ("train", "validation", "holdout")
PUBLIC_SOURCE_KIND = "public-github-pr"
BENCHMARK_SOURCE_KIND = "benchmark-derived"
HTTPS_URL = re.compile(r"^https://[^\s]+$")
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_fingerprint(cases: Iterable[dict]) -> str:
    digest = hashlib.sha256()
    for case in sorted(cases, key=lambda item: str(item["id"])):
        digest.update(json.dumps(
            case, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def repository_split(
    repository: str, salt: str = "codeevo-public-pr-v1",
    ratios: Sequence[int] = (70, 15, 15),
) -> str:
    """Assign a repository to a stable split; one repository cannot leak across splits."""
    if len(ratios) != 3 or any(int(value) < 0 for value in ratios):
        raise ValueError("split ratios must contain three non-negative integers")
    total = sum(int(value) for value in ratios)
    if total <= 0:
        raise ValueError("split ratios must have a positive total")
    digest = hashlib.sha256((salt + ":" + repository.strip().lower()).encode("utf-8"))
    bucket = int(digest.hexdigest()[:16], 16) % total
    train_end = int(ratios[0])
    validation_end = train_end + int(ratios[1])
    if bucket < train_end:
        return "train"
    if bucket < validation_end:
        return "validation"
    return "holdout"


def validate_public_provenance(case: dict) -> List[str]:
    errors: List[str] = []
    source = case.get("source") if isinstance(case.get("source"), dict) else {}
    annotation = (
        case.get("annotation") if isinstance(case.get("annotation"), dict) else {}
    )
    license_info = (
        source.get("license") if isinstance(source.get("license"), dict) else {}
    )
    required_source = (
        "public_url", "api_url", "base_sha", "head_sha", "diff_sha256",
        "repository_visibility",
    )
    for field in required_source:
        if not str(source.get(field, "")).strip():
            errors.append("source.%s is required" % field)
    repository = str(case.get("repository", "")).strip()
    pull_request = str(case.get("pull_request", "")).strip()
    expected_public_url = "https://github.com/%s/pull/%s" % (repository, pull_request)
    expected_api_url = "https://api.github.com/repos/%s/pulls/%s" % (
        repository, pull_request,
    )
    if source.get("public_url") != expected_public_url:
        errors.append("source.public_url does not match repository and pull request")
    if source.get("api_url") != expected_api_url:
        errors.append("source.api_url does not match repository and pull request")
    for field in ("annotator", "annotated_at", "methodology"):
        if not str(annotation.get(field, "")).strip():
            errors.append("annotation.%s is required" % field)
    evidence_urls = annotation.get("evidence_urls")
    if not isinstance(evidence_urls, list):
        errors.append("annotation.evidence_urls must be an array")
    elif case.get("expected_findings") and not evidence_urls:
        errors.append("risk cases require at least one annotation evidence URL")
    elif any(not HTTPS_URL.fullmatch(str(value)) for value in evidence_urls):
        errors.append("annotation.evidence_urls must contain HTTPS URLs")
    if not str(license_info.get("spdx_id", "")).strip():
        errors.append("source.license.spdx_id is required")
    if not str(license_info.get("evidence_url", "")).strip():
        errors.append("source.license.evidence_url is required")
    elif not HTTPS_URL.fullmatch(str(license_info.get("evidence_url"))):
        errors.append("source.license.evidence_url must be an HTTPS URL")
    if source.get("repository_visibility") != "public":
        errors.append("source.repository_visibility must be public")
    expected_hash = sha256_text(str(case.get("diff", "")))
    if source.get("diff_sha256") and source.get("diff_sha256") != expected_hash:
        errors.append("source.diff_sha256 does not match diff content")
    for field in ("base_sha", "head_sha"):
        value = str(source.get(field, ""))
        if value and (len(value) != 40 or any(char not in "0123456789abcdefABCDEF" for char in value)):
            errors.append("source.%s must be a 40-character Git SHA" % field)
    if source.get("base_sha") and source.get("base_sha") == source.get("head_sha"):
        errors.append("source.base_sha and source.head_sha must differ")
    return errors


def validate_benchmark_provenance(case: dict) -> List[str]:
    """Validate machine-derived truth without pretending it was human labelled."""
    errors: List[str] = []
    source = case.get("source") if isinstance(case.get("source"), dict) else {}
    benchmark = (
        source.get("benchmark") if isinstance(source.get("benchmark"), dict) else {}
    )
    derivation = (
        source.get("derivation") if isinstance(source.get("derivation"), dict) else {}
    )
    verification = (
        source.get("verification") if isinstance(source.get("verification"), dict) else {}
    )
    repository_license = (
        source.get("repository_license")
        if isinstance(source.get("repository_license"), dict) else {}
    )
    benchmark_license = (
        benchmark.get("license") if isinstance(benchmark.get("license"), dict) else {}
    )

    for field in ("public_url", "diff_sha256", "repository_visibility"):
        if not str(source.get(field, "")).strip():
            errors.append("source.%s is required" % field)
    if source.get("repository_visibility") != "public":
        errors.append("source.repository_visibility must be public")
    if not HTTPS_URL.fullmatch(str(source.get("public_url", ""))):
        errors.append("source.public_url must be an HTTPS URL")
    diff_hash = str(source.get("diff_sha256", ""))
    if diff_hash and not SHA256.fullmatch(diff_hash):
        errors.append("source.diff_sha256 must be a SHA-256 digest")
    elif diff_hash != sha256_text(str(case.get("diff", ""))):
        errors.append("source.diff_sha256 does not match diff content")

    for field in ("name", "version", "record_id", "record_sha256", "dataset_url"):
        if not str(benchmark.get(field, "")).strip():
            errors.append("source.benchmark.%s is required" % field)
    if str(benchmark.get("name", "")).lower() != "vul4j":
        errors.append("source.benchmark.name must be Vul4J")
    if benchmark.get("record_sha256") and not SHA256.fullmatch(
        str(benchmark.get("record_sha256"))
    ):
        errors.append("source.benchmark.record_sha256 must be a SHA-256 digest")
    record = benchmark.get("record")
    if not isinstance(record, dict):
        errors.append("source.benchmark.record must be an object")
    elif benchmark.get("record_sha256") != sha256_text(json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )):
        errors.append("source.benchmark.record_sha256 does not match record")
    if benchmark.get("dataset_url") and not HTTPS_URL.fullmatch(
        str(benchmark.get("dataset_url"))
    ):
        errors.append("source.benchmark.dataset_url must be an HTTPS URL")
    for label, value in (("benchmark", benchmark_license), ("repository", repository_license)):
        if not str(value.get("spdx_id", "")).strip():
            errors.append("source.%s license SPDX id is required" % label)
        evidence_url = str(value.get("evidence_url", ""))
        if not HTTPS_URL.fullmatch(evidence_url):
            errors.append("source.%s license evidence must be an HTTPS URL" % label)

    for field in (
        "patch_operation", "direction", "original_fix_url", "original_fix_sha",
        "original_parent_sha", "source_diff_sha256", "localization_method",
        "cwe_method", "severity_method", "severity_evidence_url",
    ):
        if not str(derivation.get(field, "")).strip():
            errors.append("source.derivation.%s is required" % field)
    if derivation.get("patch_operation") not in {"forward", "reverse"}:
        errors.append("source.derivation.patch_operation must be forward or reverse")
    if derivation.get("direction") not in {"security-fix", "vulnerability-introducing"}:
        errors.append("source.derivation.direction is invalid")
    if derivation.get("original_fix_sha") and not GIT_SHA.fullmatch(
        str(derivation.get("original_fix_sha"))
    ):
        errors.append("source.derivation.original_fix_sha must be a Git SHA")
    if derivation.get("original_parent_sha") and not GIT_SHA.fullmatch(
        str(derivation.get("original_parent_sha"))
    ):
        errors.append("source.derivation.original_parent_sha must be a Git SHA")
    if derivation.get("source_diff_sha256") and not SHA256.fullmatch(
        str(derivation.get("source_diff_sha256"))
    ):
        errors.append("source.derivation.source_diff_sha256 must be a SHA-256 digest")
    for field in ("original_fix_url", "severity_evidence_url"):
        if derivation.get(field) and not HTTPS_URL.fullmatch(str(derivation.get(field))):
            errors.append("source.derivation.%s must be an HTTPS URL" % field)

    for field in ("kind", "status", "command", "evidence_url"):
        if not str(verification.get(field, "")).strip():
            errors.append("source.verification.%s is required" % field)
    if verification.get("kind") != "benchmark-reproduction":
        errors.append("source.verification.kind must be benchmark-reproduction")
    if verification.get("status") not in {"published-reproducible", "locally-reproduced"}:
        errors.append("source.verification.status is not trusted")
    if verification.get("evidence_url") and not HTTPS_URL.fullmatch(
        str(verification.get("evidence_url"))
    ):
        errors.append("source.verification.evidence_url must be an HTTPS URL")

    has_findings = bool(case.get("expected_findings"))
    scoring = case.get("scoring") if isinstance(case.get("scoring"), dict) else {}
    if scoring.get("scope") != "target-cwe" or not scoring.get("target_cwes"):
        errors.append("benchmark cases must use explicit target-cwe scoring")
    if has_findings and (
        derivation.get("patch_operation") != "reverse"
        or derivation.get("direction") != "vulnerability-introducing"
    ):
        errors.append("risk benchmark cases must be reverse vulnerability-introducing patches")
    if not has_findings and (
        derivation.get("patch_operation") != "forward"
        or derivation.get("direction") != "security-fix"
    ):
        errors.append("clean benchmark cases must be forward security-fix patches")
    return errors


def validate_dataset_integrity(
    cases: Iterable[dict], require_public_provenance: bool = False,
    require_benchmark_provenance: bool = False,
) -> Dict[str, Any]:
    values = list(cases)
    errors: List[str] = []
    repository_splits: Dict[str, set] = defaultdict(set)
    hashes: Dict[str, List[str]] = defaultdict(list)
    ids = set()
    for case in values:
        case_id = str(case.get("id", ""))
        if not case_id:
            errors.append("case id is required")
        elif case_id in ids:
            errors.append("duplicate case id: %s" % case_id)
        ids.add(case_id)
        repository = str(case.get("repository", "")).strip().lower()
        split = str(case.get("split", ""))
        if split not in SPLITS:
            errors.append("%s has invalid split" % case_id)
        repository_splits[repository].add(split)
        diff_hash = sha256_text(str(case.get("diff", "")))
        hashes[diff_hash].append(case_id)
        source = case.get("source") if isinstance(case.get("source"), dict) else {}
        if require_public_provenance and source.get("kind") != PUBLIC_SOURCE_KIND:
            errors.append("%s is not a public GitHub PR" % case_id)
        if require_benchmark_provenance and source.get("kind") != BENCHMARK_SOURCE_KIND:
            errors.append("%s is not a benchmark-derived case" % case_id)
        if source.get("kind") == PUBLIC_SOURCE_KIND:
            errors.extend("%s: %s" % (case_id, item) for item in validate_public_provenance(case))
        if source.get("kind") == BENCHMARK_SOURCE_KIND:
            errors.extend(
                "%s: %s" % (case_id, item)
                for item in validate_benchmark_provenance(case)
            )

    leaked = {
        repository: sorted(splits) for repository, splits in repository_splits.items()
        if len(splits) > 1
    }
    for repository, splits in leaked.items():
        errors.append(
            "repository leakage: %s appears in %s" % (repository, ", ".join(splits))
        )
    duplicates = {
        digest: case_ids for digest, case_ids in hashes.items() if len(case_ids) > 1
    }
    for digest, case_ids in duplicates.items():
        errors.append(
            "duplicate diff %s: %s" % (digest, ", ".join(case_ids))
        )
    return {
        "valid": not errors,
        "errors": errors,
        "cases": len(values),
        "repositories": len(repository_splits),
        "split_cases": dict(Counter(str(case.get("split", "")) for case in values)),
        "split_repositories": {
            split: sum(split in splits for splits in repository_splits.values())
            for split in SPLITS
        },
        "repository_leakage": leaked,
        "duplicate_diffs": duplicates,
    }


@dataclass(frozen=True)
class DatasetManifest:
    schema_version: int
    name: str
    version: str
    dataset_sha256: str
    cases: int
    repositories: int
    split_cases: Dict[str, int]
    split_repositories: Dict[str, int]
    source_kinds: List[str]
    integrity_valid: bool

    @classmethod
    def from_cases(
        cls, cases: Iterable[dict], name: str, version: str,
        require_public_provenance: bool = False,
        require_benchmark_provenance: bool = False,
    ) -> Tuple["DatasetManifest", Dict[str, Any]]:
        values = list(cases)
        integrity = validate_dataset_integrity(
            values, require_public_provenance, require_benchmark_provenance
        )
        if not integrity["valid"]:
            raise ValueError("invalid evaluation dataset: " + "; ".join(integrity["errors"]))
        source_kinds = sorted({
            str((case.get("source") or {}).get("kind", "unknown")) for case in values
        })
        manifest = cls(
            schema_version=DATASET_MANIFEST_SCHEMA_VERSION,
            name=name.strip(), version=version.strip(),
            dataset_sha256=canonical_fingerprint(values),
            cases=len(values), repositories=integrity["repositories"],
            split_cases=integrity["split_cases"],
            split_repositories=integrity["split_repositories"],
            source_kinds=source_kinds, integrity_valid=True,
        )
        return manifest, integrity

    def to_dict(self) -> dict:
        return asdict(self)
