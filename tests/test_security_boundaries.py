import os
import tempfile
import unittest
from types import SimpleNamespace

from codeevo.auth import AuthManager
from codeevo.postgres_store import PostgresTaskStore
from codeevo.rollout import ReleaseManager
from codeevo.service import ReviewService
from codeevo.store import TaskStore


def passing_offline_evaluation():
    resource = {
        "usage_status": "available", "latency_ms_p95": 100,
        "total_tokens": 1000, "estimated_cost_usd": 0.01,
    }
    return {
        "baseline": {"score": .8, "resource_usage": resource},
        "candidate": {"score": .8, "resource_usage": dict(resource)},
    }


class SecurityBoundaryTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.store = TaskStore(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_repository_access_is_deny_by_default(self):
        self.assertFalse(self.store.repository_allowed("tenant-a", "org/private"))
        self.store.grant_repository("tenant-a", "org/private")
        self.assertTrue(self.store.repository_allowed("tenant-a", "org/private"))
        self.assertFalse(
            self.store.repository_allowed("tenant-a", "org/private", require_auto_fix=True)
        )

    def test_github_installation_state_is_tenant_bound_and_tamper_evident(self):
        auth = AuthManager(
            self.store, "s" * 32, bootstrap_username="admin",
            bootstrap_password="correct-horse", default_tenant_id="tenant-a",
        )
        token = auth.login("admin", "correct-horse")["access_token"]
        principal = auth.authenticate("Bearer " + token)
        state = auth.create_installation_state(principal)

        verified = auth.verify_installation_state(state)

        self.assertEqual("tenant-a", verified.tenant_id)
        with self.assertRaisesRegex(PermissionError, "invalid access token"):
            auth.authenticate("Bearer " + state)
        with self.assertRaises(PermissionError):
            auth.verify_installation_state(state[:-1] + ("a" if state[-1] != "a" else "b"))

    def test_guest_session_has_only_demo_read_permission(self):
        auth = AuthManager(self.store, "s" * 32)
        session = auth.guest_session("public-demo", 120)
        principal = auth.authenticate("Bearer " + session["access_token"])

        self.assertEqual("guest", principal.role)
        self.assertEqual("public-demo", principal.tenant_id)
        self.assertTrue(principal.can("demo_read"))
        for permission in ("read", "review", "fix", "manage", "audit"):
            self.assertFalse(principal.can(permission))

    def test_github_client_rejects_cross_tenant_installation(self):
        self.store.save_installation(123, "acme", "tenant-a")
        service = ReviewService.__new__(ReviewService)
        service.store = self.store
        service.github = object()
        service.settings = SimpleNamespace(
            github_app_id="app", github_private_key_path="/unused"
        )

        with self.assertRaisesRegex(PermissionError, "not authorized"):
            service.github_client_for_installation(123, "tenant-b")

    def test_shadow_observation_can_promote_a_candidate(self):
        release = ReleaseManager(self.store)
        release.configure("tenant-a", "llm-review", {
            "stable_version": 1,
            "candidate_version": 2,
            "shadow_percent": 100,
            "min_samples": 1,
            "max_disagreement_rate": 0,
            "auto_promote": True,
            "offline_evaluation": passing_offline_evaluation(),
        })

        result = release.observe_shadow(
            "tenant-a", "llm-review", "task-1", "stable",
            {"finding_keys": ["same"]}, {"finding_keys": ["same"]},
        )

        self.assertEqual("promoted", result["status"])
        observations = self.store.list_release_observations("tenant-a", "llm-review")
        self.assertEqual("task-1", observations[0]["task_id"])

    def test_postgres_store_exposes_the_release_contract(self):
        for method in (
            "save_deployment", "get_deployment", "record_deployment_result",
            "record_shadow_observation", "list_release_observations",
        ):
            self.assertTrue(callable(getattr(PostgresTaskStore, method, None)), method)


if __name__ == "__main__":
    unittest.main()
