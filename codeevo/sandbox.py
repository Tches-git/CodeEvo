"""Ephemeral, deterministic review execution for the public workbench."""
import hashlib
import re
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from .agents import MultiAgentCoordinator
from .harness import ReviewHarness
from .reviewer import ReliabilityRuleReviewer, SecurityRuleReviewer
from .store import TaskStore


GITHUB_PR_PATTERN = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)/?$"
)

SAMPLES = {
    "injection": (
        "sandbox/payment-api", None,
        "--- a/payments/settlement.py\n+++ b/payments/settlement.py\n"
        "@@ -20,2 +20,4 @@\n def settle(reference):\n-    return queue(reference)\n"
        "+    command = 'settle ' + reference\n+    subprocess.run(command, shell=True)\n"
        "+    print(reference)\n+    return True\n",
    ),
    "reliability": (
        "sandbox/job-runner", None,
        "--- a/jobs/worker.py\n+++ b/jobs/worker.py\n@@ -7,2 +7,5 @@\n"
        " def execute(job):\n-    return runner(job)\n+    try:\n+        return runner(job)\n"
        "+    except Exception:\n+        pass\n",
    ),
    "clean": (
        "sandbox/catalog-api", None,
        "--- a/catalog/items.py\n+++ b/catalog/items.py\n@@ -3,2 +3,3 @@\n"
        " def normalize(value):\n-    return value\n+    normalized = value.strip().lower()\n"
        "+    return normalized\n",
    ),
}


class _GitHubOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlparse(newurl)
        if (
            target.scheme != "https"
            or target.hostname != "api.github.com"
            or target.port not in {None, 443}
            or target.username is not None
            or target.password is not None
        ):
            raise urllib.error.HTTPError(
                newurl, 502, "GitHub redirect target was rejected", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_public_github_diff(url: str, maximum_bytes: int) -> Tuple[str, int, str]:
    match = GITHUB_PR_PATTERN.fullmatch(url.strip())
    if not match:
        raise ValueError("GitHub PR URL 格式无效，仅支持公开 github.com Pull Request")
    owner, repository, number = match.groups()
    api_url = "https://api.github.com/repos/%s/%s/pulls/%s" % (
        owner, repository, number,
    )
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github.v3.diff",
            "User-Agent": "CodeEvo-public-sandbox",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        opener = urllib.request.build_opener(_GitHubOnlyRedirectHandler())
        with opener.open(request, timeout=12) as response:
            body = response.read(maximum_bytes + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError("公开 GitHub PR 不存在或不可访问") from exc
        raise ValueError("GitHub 暂时无法提供该 PR Diff") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError("GitHub Diff 获取超时，请稍后重试") from exc
    if len(body) > maximum_bytes:
        raise ValueError("Diff 超过公开 Sandbox 大小限制")
    try:
        diff = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("GitHub Diff 不是有效 UTF-8 文本") from exc
    return "%s/%s" % (owner, repository), int(number), diff


def resolve_input(
    sample: Optional[str], diff: Optional[str], github_pr_url: Optional[str],
    maximum_bytes: int,
) -> Tuple[str, Optional[int], str, str]:
    choices = sum(bool(value) for value in (sample, diff, github_pr_url))
    if choices != 1:
        raise ValueError("必须且只能提供 sample、diff 或 github_pr_url 其中一项")
    if sample:
        repository, pull_request, value = SAMPLES[sample]
        return repository, pull_request, value, "built-in-sample"
    if github_pr_url:
        repository, pull_request, value = _fetch_public_github_diff(
            github_pr_url, maximum_bytes
        )
        return repository, pull_request, value, "public-github-pr"
    value = str(diff or "")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError("Diff 超过公开 Sandbox 大小限制")
    return "sandbox/pasted-diff", None, value, "pasted-diff"


def execute_demo_review(
    sample: Optional[str] = None, diff: Optional[str] = None,
    github_pr_url: Optional[str] = None, maximum_bytes: int = 96 * 1024,
) -> Dict[str, Any]:
    repository, pull_request, value, source = resolve_input(
        sample, diff, github_pr_url, maximum_bytes
    )
    if not value.strip():
        raise ValueError("Diff 不能为空")
    encoded = value.encode("utf-8")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="codeevo-sandbox-") as directory:
        store = TaskStore(str(Path(directory) / "sandbox.db"))
        coordinator = MultiAgentCoordinator(
            [SecurityRuleReviewer(), ReliabilityRuleReviewer()],
            max_workers=2, store=store, agent_retries=0,
            collaboration_rounds=1, agent_loop_enabled=True,
            agent_loop_max_steps=3, agent_loop_timeout_seconds=10,
        )
        harness = ReviewHarness(store, coordinator, max_steps=8, timeout_seconds=20)
        task_id = "sandbox-" + str(uuid.uuid4())
        store.create(task_id, repository, pull_request, {
            "source": source,
            "route": "local-deterministic-multi-agent",
            "model": "none",
            "model_calls": 0,
            "total_tokens": 0,
            "diff_bytes": len(encoded),
            "diff_sha256": hashlib.sha256(encoded).hexdigest(),
            "ephemeral": True,
        }, "sandbox")
        harness.run(task_id, repository, pull_request, value, "sandbox")
        task = store.get(task_id, "sandbox") or {}
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    task["input"]["latency_ms"] = elapsed_ms
    return {
        "execution": {
            "mode": "local-deterministic-sandbox",
            "ephemeral": True,
            "llm_used": False,
            "github_writeback": False,
            "duration_ms": elapsed_ms,
        },
        "task": task,
    }
