"""Auditable dual-review labelling for public GitHub pull requests."""
from __future__ import annotations

import re
import uuid
from typing import Iterable, Optional

from .evaluation_dataset import (
    CASE_SCHEMA_VERSION,
    DatasetManifest,
    repository_split,
    sha256_text,
    validate_public_provenance,
)
from .evaluation_harness import validate_case
from .store import utc_now


FINAL_STATUSES = {"approved", "exported"}
CASE_STATUSES = {
    "ready", "in_review", "needs_adjudication", "approved", "exported",
}
VERDICTS = {"risk", "clean"}
SEVERITIES = {"low", "medium", "high", "critical"}
HTTPS_URL = re.compile(r"^https://[^\s]+$")
CWE = re.compile(r"^CWE-[1-9][0-9]*$", re.IGNORECASE)
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _normal_path(path: str) -> str:
    value = str(path).replace("\\", "/").strip()
    return value[2:] if value.startswith(("a/", "b/")) else value


def normalize_findings(diff: str, verdict: str, findings: Iterable[dict]) -> list:
    """Validate labels against changed lines and return deterministic JSON values."""
    normalized = []
    for raw in findings:
        finding = {
            "path": _normal_path(raw.get("path", "")),
            "start_line": int(raw.get("start_line", 0)),
            "end_line": int(raw.get("end_line", 0)),
            "cwe": str(raw.get("cwe", "")).strip().upper(),
            "severity": str(raw.get("severity", "")).strip().lower(),
            "explanation": str(raw.get("explanation", "")).strip(),
            "evidence_url": str(raw.get("evidence_url", "")).strip(),
        }
        if not finding["path"]:
            raise ValueError("finding path is required")
        if finding["start_line"] < 1 or finding["end_line"] < 1:
            raise ValueError("finding line numbers must be positive")
        if not CWE.fullmatch(finding["cwe"]):
            raise ValueError("finding cwe must use the CWE-<number> format")
        if finding["severity"] not in SEVERITIES:
            raise ValueError("finding severity is invalid")
        if not finding["explanation"] and not finding["evidence_url"]:
            raise ValueError("finding requires an explanation or evidence URL")
        if finding["evidence_url"] and not HTTPS_URL.fullmatch(finding["evidence_url"]):
            raise ValueError("finding evidence_url must be an HTTPS URL")
        normalized.append(finding)

    verdict = str(verdict).lower()
    if verdict not in VERDICTS:
        raise ValueError("annotation verdict must be risk or clean")
    if verdict == "risk" and not normalized:
        raise ValueError("risk annotations require at least one finding")
    if verdict == "clean" and normalized:
        raise ValueError("clean annotations must submit an empty findings array")

    # Reuse the scoring harness parser to prove every label intersects an added line.
    validate_case({
        "id": "annotation-validation",
        "repository": "validation/local",
        "pull_request": 1,
        "split": "validation",
        "diff": diff,
        "expected_findings": normalized,
    })
    return sorted(normalized, key=_finding_key)


def _finding_key(finding: dict) -> tuple:
    return (
        _normal_path(finding.get("path", "")),
        int(finding.get("start_line", 0)),
        int(finding.get("end_line", 0)),
        str(finding.get("cwe", "")).upper(),
        str(finding.get("severity", "")).lower(),
    )


def labels_agree(first: dict, second: dict) -> bool:
    """Compare reproducible labels while leaving prose and evidence independent."""
    if first.get("verdict") != second.get("verdict"):
        return False
    return sorted(_finding_key(item) for item in first.get("findings", [])) == sorted(
        _finding_key(item) for item in second.get("findings", [])
    )


class AnnotationService:
    """Coordinates import, blind review, adjudication and Harness export."""

    def __init__(self, store, github, max_diff_bytes: int = 2_000_000):
        self.store = store
        self.github = github
        self.max_diff_bytes = max_diff_bytes

    def import_public_pr(
        self, tenant_id: str, actor: str, repository: str, pull_request: int,
        license_spdx: str, license_evidence_url: str,
    ) -> dict:
        repository = repository.strip()
        if not REPOSITORY.fullmatch(repository):
            raise ValueError("repository must use the owner/name format")
        if pull_request < 1:
            raise ValueError("pull_request must be positive")
        if not license_spdx.strip():
            raise ValueError("license_spdx is required")
        if not HTTPS_URL.fullmatch(license_evidence_url.strip()):
            raise ValueError("license_evidence_url must be an HTTPS URL")
        existing = self.store.find_annotation_case(
            tenant_id, repository, pull_request
        )
        if existing:
            raise ValueError("this pull request is already in the annotation queue")

        metadata = self.github.get_pull_request(repository, pull_request)
        base_repository = (metadata.get("base") or {}).get("repo") or {}
        if base_repository.get("private") is not False:
            raise ValueError("pull request is not proven to be from a public repository")
        if str(base_repository.get("full_name", "")).casefold() != repository.casefold():
            raise ValueError("GitHub pull request does not match the requested repository")
        diff_url = str(metadata.get("diff_url", "")).strip()
        if not HTTPS_URL.fullmatch(diff_url):
            raise ValueError("GitHub did not return a valid diff URL")
        diff = self.github.fetch_diff(diff_url)
        if len(diff.encode("utf-8")) > self.max_diff_bytes:
            raise ValueError("pull request diff exceeds the configured size limit")

        now = utc_now()
        source = {
            "kind": "public-github-pr",
            "public_url": "https://github.com/%s/pull/%d" % (repository, pull_request),
            "api_url": "https://api.github.com/repos/%s/pulls/%d"
            % (repository, pull_request),
            "base_sha": str((metadata.get("base") or {}).get("sha", "")),
            "head_sha": str((metadata.get("head") or {}).get("sha", "")),
            "diff_sha256": sha256_text(diff),
            "repository_visibility": "public",
            "fetched_at": now,
            "license": {
                "spdx_id": license_spdx.strip(),
                "evidence_url": license_evidence_url.strip(),
            },
        }
        # Empty provisional truth still exercises provenance and diff validation.
        provisional = {
            "schema_version": CASE_SCHEMA_VERSION,
            "id": "import-check",
            "repository": repository,
            "pull_request": pull_request,
            "split": repository_split(repository),
            "source": source,
            "annotation": {
                "annotator": "pending-dual-review",
                "annotated_at": now,
                "methodology": "Independent dual review",
                "evidence_urls": [],
            },
            "diff": diff,
            "expected_findings": [],
        }
        validate_case(provisional)
        provenance_errors = validate_public_provenance(provisional)
        if provenance_errors:
            raise ValueError(
                "invalid public PR provenance: " + "; ".join(provenance_errors)
            )
        case = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "repository": repository,
            "pull_request": pull_request,
            "split": provisional["split"],
            "status": "ready",
            "source": source,
            "diff": diff,
            "diff_sha256": source["diff_sha256"],
            "required_reviewers": 2,
            "created_by": actor,
            "created_at": now,
            "updated_at": now,
            "exported_at": None,
        }
        return self.store.create_annotation_case(case)

    def submit(
        self, tenant_id: str, case_id: str, user_id: str, username: str,
        verdict: str, findings: list, methodology: str, evidence_urls: list,
    ) -> dict:
        case = self._case(tenant_id, case_id)
        if case["status"] not in {"ready", "in_review"}:
            raise ValueError("annotation case is not accepting submissions")
        if not methodology.strip():
            raise ValueError("annotation methodology is required")
        urls = [str(value).strip() for value in evidence_urls]
        if any(not HTTPS_URL.fullmatch(value) for value in urls):
            raise ValueError("annotation evidence URLs must use HTTPS")
        normalized = normalize_findings(case["diff"], verdict, findings)
        existing = self.store.list_annotation_submissions(case_id, tenant_id)
        if any(item["annotator_id"] == user_id for item in existing):
            raise ValueError("each user may submit only one independent annotation")
        if len(existing) >= int(case["required_reviewers"]):
            raise ValueError("the required independent annotations are complete")
        submission = self.store.create_annotation_submission({
            "id": str(uuid.uuid4()),
            "case_id": case_id,
            "tenant_id": tenant_id,
            "annotator_id": user_id,
            "annotator": username,
            "verdict": verdict.lower(),
            "findings": normalized,
            "methodology": methodology.strip(),
            "evidence_urls": urls,
            "revision": 1,
            "submitted_at": utc_now(),
        })
        submissions = self.store.list_annotation_submissions(case_id, tenant_id)
        status = "in_review"
        if len(submissions) == int(case["required_reviewers"]):
            status = "approved" if labels_agree(*submissions[:2]) else "needs_adjudication"
        self.store.update_annotation_case_status(case_id, tenant_id, status, utc_now())
        current = self.store.get_annotation_case(case_id, tenant_id)
        return {"submission": submission, "case_status": current["status"]}

    def adjudicate(
        self, tenant_id: str, case_id: str, user_id: str, username: str,
        verdict: str, findings: list, rationale: str,
    ) -> dict:
        case = self._case(tenant_id, case_id)
        if case["status"] != "needs_adjudication":
            raise ValueError("annotation case does not require adjudication")
        submissions = self.store.list_annotation_submissions(case_id, tenant_id)
        if user_id in {item["annotator_id"] for item in submissions}:
            raise PermissionError("an original annotator cannot adjudicate the same case")
        if not rationale.strip():
            raise ValueError("adjudication rationale is required")
        normalized = normalize_findings(case["diff"], verdict, findings)
        result = self.store.create_annotation_adjudication({
            "id": str(uuid.uuid4()),
            "case_id": case_id,
            "tenant_id": tenant_id,
            "adjudicator_id": user_id,
            "adjudicator": username,
            "verdict": verdict.lower(),
            "findings": normalized,
            "rationale": rationale.strip(),
            "created_at": utc_now(),
        })
        self.store.update_annotation_case_status(
            case_id, tenant_id, "approved", utc_now()
        )
        return {"adjudication": result, "case_status": "approved"}

    def list_cases(
        self, tenant_id: str, principal, status: str = "", split: str = "",
        limit: int = 100,
    ) -> list:
        values = self.store.list_annotation_cases(
            tenant_id, status or None, split or None, limit
        )
        return [self._serialize(case, principal, summary=True) for case in values]

    def get_case(self, tenant_id: str, case_id: str, principal) -> dict:
        return self._serialize(self._case(tenant_id, case_id), principal)

    def export(
        self, tenant_id: str, actor: str, name: str, version: str,
        splits: Iterable[str], case_ids: Optional[Iterable[str]] = None,
    ) -> dict:
        name = name.strip()
        version = version.strip()
        if not name or not version:
            raise ValueError("dataset name and version are required")
        split_set = set(splits)
        if not split_set or not split_set.issubset({"train", "validation", "holdout"}):
            raise ValueError("export splits are invalid")
        selected_ids = set(case_ids or [])
        cases = self.store.list_annotation_cases(tenant_id, None, None, 5000)
        selected = [
            case for case in cases
            if case["status"] in FINAL_STATUSES
            and case["split"] in split_set
            and (not selected_ids or case["id"] in selected_ids)
        ]
        if selected_ids - {case["id"] for case in selected}:
            raise ValueError("all requested cases must exist and have final labels")
        if not selected:
            raise ValueError("no approved annotation cases matched the export")
        dataset = [self._evaluation_case(case) for case in selected]
        for item in dataset:
            validate_case(item)
        manifest, integrity = DatasetManifest.from_cases(
            dataset, name, version, require_public_provenance=True
        )
        exported_at = utc_now()
        record = self.store.create_annotation_export({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "name": name,
            "version": version,
            "manifest": {**manifest.to_dict(), "integrity": integrity},
            "dataset": dataset,
            "created_by": actor,
            "created_at": exported_at,
        })
        for case in selected:
            self.store.update_annotation_case_status(
                case["id"], tenant_id, "exported", exported_at,
                exported_at=exported_at,
            )
        return record

    def _case(self, tenant_id: str, case_id: str) -> dict:
        case = self.store.get_annotation_case(case_id, tenant_id)
        if not case:
            raise ValueError("annotation case not found")
        return case

    def _serialize(self, case: dict, principal, summary: bool = False) -> dict:
        submissions = self.store.list_annotation_submissions(
            case["id"], case["tenant_id"]
        )
        base = {
            key: value for key, value in case.items()
            if key not in {"source", "diff"}
        }
        base["review_progress"] = len(submissions)
        own = next(
            (item for item in submissions if item["annotator_id"] == principal.user_id),
            None,
        )
        base["my_submission"] = own
        if summary:
            return base
        base["source"] = case["source"]
        base["diff"] = case["diff"]
        review_complete = case["status"] in {
            "needs_adjudication", "approved", "exported",
        }
        can_reveal = review_complete and (
            principal.can("manage")
            or (case["split"] != "holdout" and own is not None)
        )
        if can_reveal:
            base["submissions"] = submissions
            base["adjudication"] = self.store.get_annotation_adjudication(
                case["id"], case["tenant_id"]
            )
        return base

    def _evaluation_case(self, case: dict) -> dict:
        submissions = self.store.list_annotation_submissions(
            case["id"], case["tenant_id"]
        )
        adjudication = self.store.get_annotation_adjudication(
            case["id"], case["tenant_id"]
        )
        final = adjudication or submissions[0]
        evidence_urls = sorted({
            value
            for submission in submissions
            for value in submission.get("evidence_urls", [])
        } | {
            finding.get("evidence_url", "")
            for finding in final.get("findings", [])
            if finding.get("evidence_url")
        })
        if final.get("findings") and not evidence_urls:
            evidence_urls = [case["source"]["public_url"] + "/files"]
        return {
            "schema_version": CASE_SCHEMA_VERSION,
            "id": case["id"],
            "repository": case["repository"],
            "pull_request": int(case["pull_request"]),
            "split": case["split"],
            "source": case["source"],
            "annotation": {
                "annotator": (
                    adjudication["adjudicator"] if adjudication
                    else "dual-independent-review"
                ),
                "annotated_at": (
                    adjudication["created_at"] if adjudication
                    else max(item["submitted_at"] for item in submissions)
                ),
                "methodology": (
                    "Independent dual review followed by adjudication"
                    if adjudication else "Independent dual review with semantic agreement"
                ),
                "evidence_urls": evidence_urls,
                "reviewer_count": 2,
                "submission_ids": [item["id"] for item in submissions],
                "adjudication_id": adjudication["id"] if adjudication else None,
            },
            "diff": case["diff"],
            "expected_findings": final["findings"],
        }
