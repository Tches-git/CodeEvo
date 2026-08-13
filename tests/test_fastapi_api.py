import hashlib
import hmac
import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from codeevo.api import create_app
from codeevo.config import Settings


DIFF = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+eval(data)\n"


def settings(path, auth=False, webhook_secret=""):
    return Settings(
        host="127.0.0.1", port=8080, db_path=path, max_diff_bytes=10_000,
        max_steps=8, timeout_seconds=10, llm_base_url="", llm_api_key="",
        llm_model="", github_webhook_secret=webhook_secret, github_token="",
        auto_post_review=False, skills_dir="skills", auth_required=auth,
        auth_secret="s" * 32 if auth else "",
        bootstrap_admin_username="admin" if auth else "",
        bootstrap_admin_password="correct-horse" if auth else "",
        default_tenant_id="tenant-a" if auth else "default",
    )


class FastApiTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)

    def tearDown(self):
        os.unlink(self.path)

    def test_openapi_request_id_and_security_headers(self):
        app = create_app(settings(self.path))
        with TestClient(app) as client:
            response = client.get("/health", headers={"X-Request-ID": "trace-123"})
            live = client.get("/health/live")
            ready = client.get("/health/ready")
            schema = client.get("/openapi.json").json()
            context_status = client.get(
                "/v1/repository-context/status",
                params={"repository": "org/repo"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("trace-123", response.headers["x-request-id"])
        self.assertEqual("nosniff", response.headers["x-content-type-options"])
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual("CodeEvo API", schema["info"]["title"])
        self.assertIn("/v1/reviews", schema["paths"])
        self.assertIn("/v1/repository-context/status", schema["paths"])
        self.assertGreaterEqual(len(schema["paths"]), 30)
        self.assertFalse(response.json()["repository_context_enabled"])
        self.assertEqual({"status": "ok"}, live.json())
        self.assertEqual(200, ready.status_code)
        self.assertEqual({"persistence": True, "queue": True}, ready.json()["checks"])
        self.assertFalse(context_status.json()["available"])

    def test_readiness_fails_closed_when_a_dependency_is_unavailable(self):
        app = create_app(settings(self.path))
        app.state.service.store.ping = lambda: False

        with TestClient(app) as client:
            live = client.get("/health/live")
            ready = client.get("/health/ready")

        self.assertEqual(200, live.status_code)
        self.assertEqual(503, ready.status_code)
        self.assertEqual("unavailable", ready.json()["status"])
        self.assertFalse(ready.json()["checks"]["persistence"])

    def test_review_feedback_and_validation_flow(self):
        app = create_app(settings(self.path))
        sensitive_value = "do-not-leak-this-review-payload"
        with TestClient(app) as client:
            invalid = client.post("/v1/reviews", json={
                "repository": "org/repo", "diff": DIFF,
                "pull_request": sensitive_value, "unexpected": True,
            })
            created = client.post("/v1/reviews", json={
                "repository": "org/repo", "pull_request": 3, "diff": DIFF,
            })
            task_id = created.json()["task_id"]
            task = client.get("/v1/tasks/" + task_id)
            report = client.get("/v1/tasks/" + task_id + "/report")
            feedback = client.post("/v1/tasks/" + task_id + "/feedback", json={
                "category": "accepted",
                "finding": created.json()["report"]["findings"][0],
                "note": "confirmed",
            })
            history = client.get("/v1/tasks/" + task_id + "/feedback")

        self.assertEqual(422, invalid.status_code)
        self.assertEqual("request validation failed", invalid.json()["error"])
        self.assertNotIn(sensitive_value, invalid.text)
        self.assertNotIn("input", invalid.json()["detail"][0])
        self.assertEqual(201, created.status_code)
        self.assertEqual("SUCCESS", task.json()["state"])
        self.assertIn("# CodeEvo PR Review", report.text)
        self.assertEqual(201, feedback.status_code)
        self.assertEqual("accepted", history.json()["cases"][0]["category"])

    def test_authentication_repository_policy_and_installation_callback(self):
        app = create_app(settings(self.path, auth=True))
        service = app.state.service
        service.store.grant_repository("tenant-a", "org/private")
        with TestClient(app) as client:
            denied = client.get("/api/dashboard")
            login = client.post("/v1/auth/login", json={
                "username": "admin", "password": "correct-horse",
            })
            token = login.json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            dashboard = client.get("/api/dashboard", headers=headers)
            review = client.post("/v1/reviews", headers=headers, json={
                "repository": "org/private", "diff": DIFF,
            })
            blocked_repository = client.post("/v1/reviews", headers=headers, json={
                "repository": "org/not-granted", "diff": DIFF,
            })
            principal = service.auth.authenticate("Bearer " + token)
            state = service.auth.create_installation_state(principal)
            callback = client.get(
                "/github/setup",
                params={"installation_id": 321, "account": "acme", "state": state},
                follow_redirects=False,
            )

        self.assertEqual(401, denied.status_code)
        self.assertEqual(200, login.status_code)
        self.assertEqual(200, dashboard.status_code)
        self.assertEqual(201, review.status_code)
        self.assertEqual(403, blocked_repository.status_code)
        self.assertEqual(302, callback.status_code)
        self.assertEqual("tenant-a", service.store.installation_tenant(321))

    def test_webhook_signature_is_required_even_for_ignored_events(self):
        secret = "webhook-secret"
        app = create_app(settings(self.path, webhook_secret=secret))
        body = json.dumps({"ref": "main"}, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        base_headers = {
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-1",
        }
        with TestClient(app) as client:
            invalid = client.post(
                "/webhooks/github", content=body,
                headers={**base_headers, "X-Hub-Signature-256": "sha256=bad"},
            )
            ignored = client.post(
                "/webhooks/github", content=body,
                headers={**base_headers, "X-Hub-Signature-256": signature},
            )

        self.assertEqual(401, invalid.status_code)
        self.assertEqual(202, ignored.status_code)
        self.assertTrue(ignored.json()["ignored"])

    def test_dead_letters_are_filtered_by_tenant(self):
        app = create_app(settings(self.path, auth=True))
        service = app.state.service
        service.queue._memory_dlq.extend([
            {"message_id": "a", "payload": {"tenant_id": "tenant-a"}},
            {"message_id": "b", "payload": {"tenant_id": "tenant-b"}},
        ])
        with TestClient(app) as client:
            login = client.post("/v1/auth/login", json={
                "username": "admin", "password": "correct-horse",
            })
            response = client.get(
                "/api/queue/dead-letters",
                headers={"Authorization": "Bearer " + login.json()["access_token"]},
            )

        self.assertEqual(["a"], [item["message_id"] for item in response.json()["messages"]])

    def test_routing_policy_candidate_must_pass_resource_gate_before_shadow(self):
        app = create_app(settings(self.path))
        baseline = {
            "score": 0.80, "precision": 0.80, "recall": 0.80,
            "resource_usage": {
                "usage_status": "available", "latency_ms_p95": 100.0,
                "total_tokens": 1000, "estimated_cost_usd": 0.01,
            },
        }
        candidate = {
            "score": 0.82, "precision": 0.82, "recall": 0.82,
            "resource_usage": {
                "usage_status": "available", "latency_ms_p95": 110.0,
                "total_tokens": 1500, "estimated_cost_usd": 0.011,
            },
        }
        with TestClient(app) as client:
            response = client.post("/v1/evaluation/routing-policy", json={
                "baseline": baseline, "candidate": candidate,
                "require_improvement": True,
            })

        self.assertEqual(200, response.status_code)
        self.assertEqual("rejected", response.json()["decision"])
        self.assertFalse(response.json()["gates"]["total_tokens"]["passed"])

    def test_login_is_rate_limited_without_trusting_forwarded_headers(self):
        base = settings(self.path, auth=True)
        limited = base.__class__(**{
            **base.__dict__, "login_max_attempts": 2, "login_lockout_seconds": 60,
        })
        app = create_app(limited)
        payload = {"username": "admin", "password": "wrong-password"}
        with TestClient(app) as client:
            first = client.post(
                "/v1/auth/login", json=payload,
                headers={"X-Forwarded-For": "203.0.113.1"},
            )
            second = client.post(
                "/v1/auth/login", json=payload,
                headers={"X-Forwarded-For": "203.0.113.2"},
            )
            blocked = client.post("/v1/auth/login", json=payload)

        self.assertEqual(401, first.status_code)
        self.assertEqual(401, second.status_code)
        self.assertEqual(429, blocked.status_code)
        self.assertGreaterEqual(int(blocked.headers["retry-after"]), 1)


if __name__ == "__main__":
    unittest.main()
