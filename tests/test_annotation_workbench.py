import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from codeevo.api import create_app
from codeevo.auth import hash_password
from codeevo.config import Settings
from codeevo.evaluation_dataset import repository_split
from codeevo.evaluation_harness import load_jsonl


DIFF = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+eval(data)\n"


class FakeGitHub:
    def __init__(self, repository):
        self.repository = repository

    def get_pull_request(self, repository, number):
        assert repository == self.repository
        return {
            "diff_url": "https://github.com/%s/pull/%d.diff" % (repository, number),
            "base": {
                "sha": "a" * 40,
                "repo": {"private": False, "full_name": repository},
            },
            "head": {"sha": "b" * 40},
        }

    def fetch_diff(self, _url):
        return DIFF


def settings(path):
    return Settings(
        host="127.0.0.1", port=8080, db_path=path, max_diff_bytes=100_000,
        max_steps=8, timeout_seconds=10, llm_base_url="", llm_api_key="",
        llm_model="", github_webhook_secret="", github_token="",
        auto_post_review=False, skills_dir="skills", auth_required=True,
        auth_secret="s" * 32, bootstrap_admin_username="admin",
        bootstrap_admin_password="correct-horse", default_tenant_id="tenant-a",
    )


def non_holdout_repository():
    for number in range(100):
        repository = "public-lab/repo-%d" % number
        if repository_split(repository) != "holdout":
            return repository
    raise AssertionError("a non-holdout repository should exist")


class AnnotationWorkbenchTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.repository = non_holdout_repository()
        self.app = create_app(settings(self.path))
        store = self.app.state.service.store
        store.create_user(
            "reviewer-one", "lin-qiao", hash_password("reviewer-one-password"),
            "tenant-a", "maintainer",
        )
        store.create_user(
            "reviewer-two", "zhou-ning", hash_password("reviewer-two-password"),
            "tenant-a", "maintainer",
        )
        self.app.state.service.annotations.github = FakeGitHub(self.repository)

    def tearDown(self):
        os.unlink(self.path)

    @staticmethod
    def login(client, username, password):
        response = client.post("/v1/auth/login", json={
            "username": username, "password": password,
        })
        assert response.status_code == 200, response.text
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def test_blind_dual_review_adjudication_and_harness_export(self):
        with TestClient(self.app) as client:
            admin = self.login(client, "admin", "correct-horse")
            first = self.login(client, "lin-qiao", "reviewer-one-password")
            second = self.login(client, "zhou-ning", "reviewer-two-password")
            imported = client.post(
                "/v1/annotations/cases/import", headers=admin, json={
                    "repository": self.repository,
                    "pull_request": 17,
                    "license_spdx": "MIT",
                    "license_evidence_url": "https://github.com/%s/blob/main/LICENSE"
                    % self.repository,
                },
            )
            self.assertEqual(201, imported.status_code, imported.text)
            case_id = imported.json()["id"]

            first_result = client.post(
                "/v1/annotations/cases/%s/submissions" % case_id,
                headers=first,
                json={
                    "verdict": "clean", "findings": [],
                    "methodology": "Manual changed-line security review",
                    "evidence_urls": [],
                },
            )
            self.assertEqual("in_review", first_result.json()["case_status"])

            second_blind_view = client.get(
                "/v1/annotations/cases/%s" % case_id, headers=second
            )
            self.assertNotIn("submissions", second_blind_view.json())
            self.assertIsNone(second_blind_view.json()["my_submission"])

            duplicate = client.post(
                "/v1/annotations/cases/%s/submissions" % case_id,
                headers=first,
                json={
                    "verdict": "clean", "findings": [],
                    "methodology": "Repeated submission", "evidence_urls": [],
                },
            )
            self.assertEqual(400, duplicate.status_code)

            finding = {
                "path": "app.py", "start_line": 1, "end_line": 1,
                "cwe": "CWE-95", "severity": "critical",
                "explanation": "Untrusted input reaches eval.",
                "evidence_url": "",
            }
            second_result = client.post(
                "/v1/annotations/cases/%s/submissions" % case_id,
                headers=second,
                json={
                    "verdict": "risk", "findings": [finding],
                    "methodology": "Manual data-flow review", "evidence_urls": [],
                },
            )
            self.assertEqual(
                "needs_adjudication", second_result.json()["case_status"]
            )

            forbidden = client.post(
                "/v1/annotations/cases/%s/adjudications" % case_id,
                headers=first,
                json={
                    "verdict": "risk", "findings": [finding],
                    "rationale": "The risk is reproducible.",
                },
            )
            self.assertEqual(403, forbidden.status_code)

            adjudicated = client.post(
                "/v1/annotations/cases/%s/adjudications" % case_id,
                headers=admin,
                json={
                    "verdict": "risk", "findings": [finding],
                    "rationale": "The added eval call accepts untrusted input.",
                },
            )
            self.assertEqual(201, adjudicated.status_code, adjudicated.text)
            self.assertEqual("approved", adjudicated.json()["case_status"])

            exported = client.post(
                "/v1/annotations/exports", headers=admin, json={
                    "name": "public-pr-labels", "version": "0.6.0",
                    "splits": [repository_split(self.repository)],
                    "case_ids": [case_id],
                },
            )
            self.assertEqual(201, exported.status_code, exported.text)
            download = client.get(exported.json()["download_url"], headers=admin)
            self.assertEqual(200, download.status_code)
            self.assertEqual(
                exported.json()["manifest"]["dataset_sha256"],
                download.headers["x-dataset-sha256"],
            )
            reexported = client.post(
                "/v1/annotations/exports", headers=admin, json={
                    "name": "public-pr-labels", "version": "0.6.1",
                    "splits": [repository_split(self.repository)],
                    "case_ids": [case_id],
                },
            )
            self.assertEqual(201, reexported.status_code, reexported.text)

        handle, dataset_path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as output:
                output.write(download.text)
            dataset = load_jsonl(dataset_path)
            self.assertEqual(1, len(dataset))
            self.assertEqual("CWE-95", dataset[0]["expected_findings"][0]["cwe"])
            self.assertEqual(2, dataset[0]["annotation"]["reviewer_count"])
        finally:
            os.unlink(dataset_path)

        actions = {
            item["action"]
            for item in self.app.state.service.store.list_audit("tenant-a", 100)
        }
        self.assertIn("annotation.case.import", actions)
        self.assertIn("annotation.adjudication.create", actions)
        self.assertIn("annotation.dataset.export", actions)

    def test_matching_labels_are_approved_without_adjudication(self):
        with TestClient(self.app) as client:
            admin = self.login(client, "admin", "correct-horse")
            first = self.login(client, "lin-qiao", "reviewer-one-password")
            second = self.login(client, "zhou-ning", "reviewer-two-password")
            imported = client.post(
                "/v1/annotations/cases/import", headers=admin, json={
                    "repository": self.repository, "pull_request": 18,
                    "license_spdx": "MIT",
                    "license_evidence_url": "https://github.com/%s/blob/main/LICENSE"
                    % self.repository,
                },
            )
            case_id = imported.json()["id"]
            payload = {
                "verdict": "clean", "findings": [],
                "methodology": "Independent review", "evidence_urls": [],
            }
            client.post(
                "/v1/annotations/cases/%s/submissions" % case_id,
                headers=first, json=payload,
            )
            result = client.post(
                "/v1/annotations/cases/%s/submissions" % case_id,
                headers=second, json={**payload, "methodology": "Second independent review"},
            )
            self.assertEqual("approved", result.json()["case_status"])


if __name__ == "__main__":
    unittest.main()
