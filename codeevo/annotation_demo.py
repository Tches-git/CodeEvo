"""Offline annotation-workbench demo records with non-public provenance."""
import argparse
import uuid

from .auth import hash_password
from .evaluation_dataset import repository_split, sha256_text
from .store import TaskStore, utc_now


DIFFS = (
    "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+eval(data)\n",
    "--- a/auth.py\n+++ b/auth.py\n@@ -5 +5 @@\n-token = load_secret()\n+token = \"demo-secret\"\n",
    "--- a/api.py\n+++ b/api.py\n@@ -8 +8 @@\n-query = safe_query(value)\n+query = \"SELECT * FROM users WHERE id = \" + value\n",
    "--- a/service.py\n+++ b/service.py\n@@ -2 +2 @@\n-return response\n+return sanitize(response)\n",
)


def finding(path: str, line: int, cwe: str, severity: str) -> dict:
    return {
        "path": path, "start_line": line, "end_line": line,
        "cwe": cwe, "severity": severity,
        "explanation": "Offline demo label for the annotation workflow.",
        "evidence_url": "",
    }


def seed(path: str, reviewer_password: str = "") -> int:
    store = TaskStore(path)
    if reviewer_password:
        if len(reviewer_password) < 10:
            raise ValueError("reviewer password must contain at least 10 characters")
        password_hash = hash_password(reviewer_password)
        store.create_user(
            "demo-reviewer-a", "demo-reviewer-a", password_hash,
            "default", "maintainer",
        )
        store.create_user(
            "demo-reviewer-b", "demo-reviewer-b", password_hash,
            "default", "maintainer",
        )

    states = ("ready", "in_review", "needs_adjudication", "approved")
    repositories = (
        "demo-lab/parser", "demo-lab/identity", "demo-lab/data-api",
        "demo-lab/output-service",
    )
    created = 0
    for index, (status, repository, diff) in enumerate(
        zip(states, repositories, DIFFS), 1
    ):
        if store.find_annotation_case("default", repository, index):
            continue
        now = utc_now()
        case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "codeevo-demo:" + repository))
        store.create_annotation_case({
            "id": case_id,
            "tenant_id": "default",
            "repository": repository,
            "pull_request": index,
            "split": repository_split(repository),
            "status": "ready",
            "source": {
                "kind": "demo-fixture",
                "public_url": "https://example.invalid/%s/pull/%d" % (repository, index),
                "api_url": "https://example.invalid/api/%s/pulls/%d" % (repository, index),
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "diff_sha256": sha256_text(diff),
                "repository_visibility": "demo-only",
                "fetched_at": now,
                "license": {
                    "spdx_id": "NOASSERTION",
                    "evidence_url": "https://example.invalid/demo-license",
                },
            },
            "diff": diff,
            "diff_sha256": sha256_text(diff),
            "required_reviewers": 2,
            "created_by": "demo-seed",
            "created_at": now,
            "updated_at": now,
            "exported_at": None,
        })
        created += 1
        if status == "ready":
            continue
        labels = [] if index == 4 else [
            finding(
                "auth.py" if index == 2 else "api.py", 5 if index == 2 else 8,
                "CWE-798" if index == 2 else "CWE-89", "high",
            )
        ]
        first_verdict = "clean" if index in {3, 4} else "risk"
        first_findings = [] if first_verdict == "clean" else labels
        store.create_annotation_submission({
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, case_id + ":reviewer-a")),
            "case_id": case_id, "tenant_id": "default",
            "annotator_id": "demo-reviewer-a", "annotator": "demo-reviewer-a",
            "verdict": first_verdict, "findings": first_findings,
            "methodology": "Offline demonstration review A", "evidence_urls": [],
            "revision": 1, "submitted_at": now,
        })
        store.update_annotation_case_status(case_id, "default", "in_review", now)
        if status == "in_review":
            continue
        second_verdict = "risk" if index == 3 else "clean"
        second_findings = labels if second_verdict == "risk" else []
        store.create_annotation_submission({
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, case_id + ":reviewer-b")),
            "case_id": case_id, "tenant_id": "default",
            "annotator_id": "demo-reviewer-b", "annotator": "demo-reviewer-b",
            "verdict": second_verdict, "findings": second_findings,
            "methodology": "Offline demonstration review B", "evidence_urls": [],
            "revision": 1, "submitted_at": now,
        })
        store.update_annotation_case_status(case_id, "default", status, now)
    return created


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed clearly marked offline annotation demo records"
    )
    parser.add_argument("database", help="SQLite database path")
    parser.add_argument(
        "--reviewer-password", default="",
        help="Optionally create two demo maintainer logins with this password",
    )
    args = parser.parse_args()
    created = seed(args.database, args.reviewer_password)
    print("seeded %d annotation demo cases" % created)
    print("demo-fixture records intentionally fail the public provenance export gate")


if __name__ == "__main__":
    main()
