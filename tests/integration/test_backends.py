import hashlib
import hmac
import json
import os
import tempfile
import threading
import unittest
import uuid

from fastapi.testclient import TestClient

from codeevo.api import create_app
from codeevo.config import Settings
from codeevo.repository import create_repository
from codeevo.task_queue import TaskQueue


DATABASE_URL = os.getenv("CODEEVO_INTEGRATION_DATABASE_URL", "")
REDIS_URL = os.getenv("CODEEVO_INTEGRATION_REDIS_URL", "")


@unittest.skipUnless(DATABASE_URL and REDIS_URL, "integration backends are not configured")
class BackendIntegrationTests(unittest.TestCase):
    def test_postgres_repository_migrates_and_round_trips_task(self):
        repository = create_repository(DATABASE_URL, "unused.db", auto_migrate=True)
        task_id = "integration-" + uuid.uuid4().hex
        try:
            repository.create(
                task_id,
                "integration/repository",
                7,
                {"source": "integration-test"},
                "tenant-integration",
            )
            task = repository.get(task_id, "tenant-integration")
        finally:
            repository.close()

        self.assertEqual("PENDING", task["state"])
        self.assertEqual("integration/repository", task["repository"])
        self.assertEqual("integration-test", task["input"]["source"])

    def test_postgres_annotation_repository_round_trips_dual_review(self):
        repository = create_repository(DATABASE_URL, "unused.db", auto_migrate=True)
        suffix = uuid.uuid4().hex
        case_id = "annotation-" + suffix
        tenant_id = "tenant-annotation-" + suffix
        now = "2026-08-12T00:00:00+00:00"
        diff = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+eval(data)\n"
        case = {
            "id": case_id, "tenant_id": tenant_id,
            "repository": "integration/annotation-" + suffix,
            "pull_request": 11, "split": "validation", "status": "ready",
            "source": {"kind": "integration-test"}, "diff": diff,
            "diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
            "required_reviewers": 2, "created_by": "integration",
            "created_at": now, "updated_at": now, "exported_at": None,
        }
        try:
            repository.create_annotation_case(case)
            repository.create_annotation_submission({
                "id": "submission-" + suffix, "case_id": case_id,
                "tenant_id": tenant_id, "annotator_id": "reviewer-a",
                "annotator": "reviewer-a", "verdict": "clean", "findings": [],
                "methodology": "Integration review", "evidence_urls": [],
                "revision": 1, "submitted_at": now,
            })
            stored = repository.get_annotation_case(case_id, tenant_id)
            submissions = repository.list_annotation_submissions(case_id, tenant_id)
        finally:
            repository.close()

        self.assertEqual("integration-test", stored["source"]["kind"])
        self.assertEqual("reviewer-a", submissions[0]["annotator"])
        self.assertEqual([], submissions[0]["findings"])

    def test_redis_stream_delivers_and_acknowledges(self):
        delivered = threading.Event()
        received = []

        def handler(payload):
            received.append(payload)
            delivered.set()

        queue = TaskQueue(handler, workers=1, redis_url=REDIS_URL)
        try:
            queue.submit({"task_id": "queue-" + uuid.uuid4().hex})
            self.assertTrue(delivered.wait(8), "Redis worker did not deliver the task")
        finally:
            queue.close()

        self.assertEqual(1, len(received))
        self.assertEqual("redis-streams", queue.backend)

    def test_signed_webhook_reaches_fastapi_with_production_backends(self):
        secret = "integration-webhook-secret"
        handle, fallback_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        settings = Settings(
            host="127.0.0.1",
            port=8080,
            db_path=fallback_path,
            max_diff_bytes=10_000,
            max_steps=8,
            timeout_seconds=10,
            llm_base_url="",
            llm_api_key="",
            llm_model="",
            github_webhook_secret=secret,
            github_token="",
            auto_post_review=False,
            database_url=DATABASE_URL,
            redis_url=REDIS_URL,
            skills_dir="skills",
        )
        body = json.dumps({"ref": "main"}, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        try:
            with TestClient(create_app(settings)) as client:
                response = client.post(
                    "/webhooks/github",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-GitHub-Event": "push",
                        "X-GitHub-Delivery": "integration-" + uuid.uuid4().hex,
                        "X-Hub-Signature-256": signature,
                    },
                )
        finally:
            os.unlink(fallback_path)

        self.assertEqual(202, response.status_code)
        self.assertTrue(response.json()["ignored"])


if __name__ == "__main__":
    unittest.main()
