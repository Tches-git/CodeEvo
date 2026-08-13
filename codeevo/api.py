"""FastAPI transport for CodeEvo's review and AgentOps services."""
import hashlib
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional
from urllib.parse import quote

from fastapi import (
    Depends, FastAPI, Header, HTTPException, Path as ApiPath, Query, Request, Response,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api_schemas import (
    AnnotationAdjudicationRequest,
    AnnotationExportRequest,
    AnnotationImportRequest,
    AnnotationSubmissionRequest,
    DeadLetterReplayRequest,
    DeploymentRequest,
    EvaluationCaseRequest,
    EvolutionAutoRequest,
    EvolutionProposalRequest,
    FeedbackRequest,
    FixRequest,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    ReviewRequest,
    ReviewSubmission,
    ReadinessResponse,
    RoutingPolicyEvaluationRequest,
    SkillEvolutionAutoRequest,
    SkillEvolutionProposalRequest,
)
from .auth import Principal
from .config import Settings
from .github import verify_signature
from .metrics import metrics
from .network import TrustedProxyResolver
from .rate_limit import LoginRateLimiter
from .report import to_markdown
from .service import ReviewService


WEB_ROOT = Path(__file__).resolve().parent / "web"
SKILL_NAME_PATTERN = r"^[a-z0-9_-]+$"
VERSIONED_SKILL_PATTERN = r"^[A-Za-z0-9_-]+$"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
logger = logging.getLogger("codeevo.api")


def create_app(
    settings: Optional[Settings] = None,
    service: Optional[ReviewService] = None,
) -> FastAPI:
    """Build an application with injectable settings/service for integration tests."""
    config = settings or Settings.from_env()
    review_service = service or ReviewService(config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        review_service.queue.close()
        close_store = getattr(review_service.store, "close", None)
        if close_store:
            close_store()

    app = FastAPI(
        title="CodeEvo API",
        description="Evaluation-gated multi-agent code review and controlled evolution API.",
        version="0.9.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = config
    app.state.service = review_service
    app.state.login_limiter = LoginRateLimiter(
        config.login_max_attempts, config.login_window_seconds,
        config.login_lockout_seconds,
    )
    app.state.proxy_resolver = TrustedProxyResolver(config.trusted_proxy_cidrs)

    def request_id(request: Request) -> str:
        return str(getattr(request.state, "request_id", ""))

    def error_response(request: Request, status_code: int, error: str, detail: Any = None):
        body: Dict[str, Any] = {"error": error, "request_id": request_id(request)}
        if detail is not None:
            body["detail"] = detail
        return JSONResponse(status_code=status_code, content=jsonable_encoder(body))

    @app.middleware("http")
    async def transport_guard(request: Request, call_next):
        started = time.perf_counter()
        supplied_id = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            supplied_id if REQUEST_ID_PATTERN.fullmatch(supplied_id) else str(uuid.uuid4())
        )
        response = None
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                length = int(content_length)
            except ValueError:
                response = error_response(request, 400, "invalid Content-Length")
            else:
                if length < 0:
                    response = error_response(request, 400, "invalid Content-Length")
                elif length > config.max_diff_bytes + 256 * 1024:
                    response = error_response(request, 413, "request body is too large")
        if response is None:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        if app.state.proxy_resolver.scheme(request) == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        logger.info(
            "request.completed",
            extra={
                "event": "http.request.completed",
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "client_ip": app.state.proxy_resolver.client_ip(request),
            },
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        response = error_response(request, exc.status_code, str(exc.detail))
        for key, value in (exc.headers or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Never echo request values: diffs, prompts and passwords may be sensitive.
        detail = [
            {"type": item.get("type"), "loc": item.get("loc"), "msg": item.get("msg")}
            for item in exc.errors()
        ]
        return error_response(request, 422, "request validation failed", detail)

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError):
        return error_response(request, 400, str(exc))

    @app.exception_handler(PermissionError)
    async def permission_error(request: Request, exc: PermissionError):
        return error_response(request, 403, str(exc))

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, _exc: Exception):
        metrics.inc("http_errors_total")
        return error_response(request, 500, "operation failed")

    def authenticate(authorization: str = Header(default="")) -> Principal:
        if not config.auth_required:
            return Principal(
                "local", "local-development", config.default_tenant_id, "admin"
            )
        try:
            return review_service.auth.authenticate(authorization)
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def require(permission: str):
        def dependency(principal: Principal = Depends(authenticate)) -> Principal:
            if not principal.can(permission):
                raise HTTPException(status_code=403, detail="permission denied")
            return principal
        return dependency

    read_principal = require("read")
    review_principal = require("review")
    fix_principal = require("fix")
    manage_principal = require("manage")
    audit_principal = require("audit")

    def tenant_dead_letters(tenant_id: str, limit: int) -> list:
        values = review_service.queue.dead_letters(500)
        return [
            item for item in values
            if (item.get("payload") or {}).get("tenant_id", "default") == tenant_id
        ][:limit]

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_ROOT / "index.html")

    app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    def health():
        return {
            "status": "ok",
            "reviewer": review_service.reviewer.name,
            "runtime": review_service.harness.name,
            "queue": review_service.queue.backend,
            "llm_provider": review_service.llm_config.get("provider", "local"),
            "llm_model": review_service.llm_config.get("model", ""),
            "repository_context_enabled": review_service.workspace_resolver.enabled,
        }

    @app.get("/health/live", tags=["operations"])
    def liveness():
        return {"status": "ok"}

    @app.get(
        "/health/ready", response_model=ReadinessResponse,
        responses={503: {"model": ReadinessResponse}}, tags=["operations"],
    )
    def readiness(response: Response):
        checks = review_service.readiness()
        ready = all(checks.values())
        if not ready:
            response.status_code = 503
        return {"status": "ok" if ready else "unavailable", "checks": checks}

    @app.post("/v1/auth/login", response_model=LoginResponse, tags=["authentication"])
    def login(request: Request, payload: LoginRequest):
        if not config.auth_required:
            raise HTTPException(status_code=409, detail="authentication is disabled")
        client_host = app.state.proxy_resolver.client_ip(request)
        limit_key = (client_host, payload.username.casefold())
        retry_after = app.state.login_limiter.retry_after(limit_key)
        if retry_after:
            raise HTTPException(
                status_code=429, detail="too many login attempts",
                headers={"Retry-After": str(retry_after)},
            )
        try:
            result = review_service.auth.login(
                payload.username, payload.password, payload.tenant_id
            )
        except PermissionError as exc:
            app.state.login_limiter.record_failure(limit_key)
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        app.state.login_limiter.reset(limit_key)
        return result

    @app.post("/v1/reviews", response_model=ReviewSubmission, tags=["reviews"])
    def create_review(
        response: Response,
        payload: ReviewRequest,
        async_review: bool = Query(default=False, alias="async"),
        principal: Principal = Depends(review_principal),
    ):
        args = (payload.repository, payload.diff, payload.pull_request)
        result = (
            review_service.enqueue_review(*args, tenant_id=principal.tenant_id)
            if async_review else
            review_service.create_review(*args, tenant_id=principal.tenant_id)
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "review.create",
            payload.repository, {"async": async_review},
        )
        response.status_code = 202 if async_review else 201
        return result

    @app.get("/v1/tasks/{task_id}", tags=["reviews"])
    def get_task(task_id: str, principal: Principal = Depends(read_principal)):
        task = review_service.store.get(task_id, principal.tenant_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        return task

    @app.get("/v1/tasks/{task_id}/report", tags=["reviews"])
    def get_report(task_id: str, principal: Principal = Depends(read_principal)):
        task = review_service.store.get(task_id, principal.tenant_id)
        if not task or not task.get("report"):
            raise HTTPException(status_code=404, detail="task or report not found")
        return PlainTextResponse(to_markdown(task["report"]), media_type="text/markdown")

    @app.get("/v1/tasks/{task_id}/feedback", tags=["feedback"])
    def get_feedback(task_id: str, principal: Principal = Depends(review_principal)):
        if not review_service.store.get(task_id, principal.tenant_id):
            raise HTTPException(status_code=404, detail="task not found")
        return {"cases": review_service.store.list_task_failure_cases(
            task_id, principal.tenant_id
        )}

    @app.post("/v1/tasks/{task_id}/feedback", status_code=201, tags=["feedback"])
    def record_feedback(
        task_id: str, payload: FeedbackRequest,
        principal: Principal = Depends(review_principal),
    ):
        result = review_service.record_feedback(
            task_id, payload.category, payload.finding, payload.note, principal.tenant_id
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "feedback.record", task_id,
            {"category": result["category"]},
        )
        return result

    @app.post("/v1/tasks/{task_id}/fix", status_code=201, tags=["repairs"])
    def create_fix(
        task_id: str, payload: FixRequest,
        principal: Principal = Depends(fix_principal),
    ):
        result = review_service.create_fix(
            task_id, payload.installation_id, principal.tenant_id
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "repair.create", task_id,
            {"branch": result.get("branch")},
        )
        return result

    @app.post("/v1/tasks/{task_id}/cancel", status_code=202, tags=["reviews"])
    def cancel_task(task_id: str, principal: Principal = Depends(review_principal)):
        ok = review_service.cancel_task(task_id, principal.tenant_id)
        if not ok:
            raise HTTPException(status_code=404, detail="task not found")
        review_service.store.audit(
            principal.tenant_id, principal.username, "task.cancel", task_id
        )
        return {"cancel_requested": True}

    @app.post("/v1/tasks/{task_id}/resume", status_code=202, tags=["reviews"])
    def resume_task(task_id: str, principal: Principal = Depends(review_principal)):
        result = review_service.resume_task(task_id, principal.tenant_id)
        review_service.store.audit(
            principal.tenant_id, principal.username, "task.resume", task_id
        )
        return result

    @app.post("/webhooks/github", status_code=202, tags=["integrations"])
    async def github_webhook(
        request: Request,
        github_event: str = Header(default="", alias="X-GitHub-Event"),
        signature: str = Header(default="", alias="X-Hub-Signature-256"),
        delivery_id: str = Header(default="", alias="X-GitHub-Delivery"),
    ):
        body = await request.body()
        if not config.github_webhook_secret:
            raise HTTPException(
                status_code=503, detail="GitHub webhook secret is not configured"
            )
        if not verify_signature(config.github_webhook_secret, body, signature):
            raise HTTPException(status_code=401, detail="invalid webhook signature")
        if not delivery_id:
            raise HTTPException(status_code=400, detail="X-GitHub-Delivery is required")
        if github_event != "pull_request":
            return {"ignored": True, "reason": "unsupported GitHub event"}
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON root must be an object")
        updated_at = (payload.get("pull_request") or {}).get("updated_at")
        if updated_at:
            try:
                event_time = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail="invalid pull_request.updated_at"
                ) from exc
            if event_time.tzinfo is None:
                raise HTTPException(
                    status_code=400, detail="pull_request.updated_at must include a timezone"
                )
            age = abs((datetime.now(timezone.utc) - event_time).total_seconds())
            if age > config.webhook_max_age_seconds:
                raise HTTPException(
                    status_code=409, detail="webhook is outside the replay window"
                )
        return review_service.handle_github_pull_request(
            payload, delivery_id, hashlib.sha256(body).hexdigest()
        )

    @app.get("/github/install", include_in_schema=False)
    def github_install(principal: Principal = Depends(manage_principal)):
        if not config.github_app_slug:
            raise HTTPException(
                status_code=503, detail="CODEEVO_GITHUB_APP_SLUG is not configured"
            )
        if not config.auth_required:
            raise HTTPException(
                status_code=409,
                detail="authentication must be enabled for GitHub App installation",
            )
        state = review_service.auth.create_installation_state(principal)
        location = "https://github.com/apps/%s/installations/new?state=%s" % (
            quote(config.github_app_slug, safe="-"), quote(state, safe=""),
        )
        return RedirectResponse(location, status_code=302)

    @app.get("/github/setup", include_in_schema=False)
    def github_setup(
        installation_id: int = Query(ge=1), state: str = Query(min_length=1),
        account: str = Query(default="github-app", max_length=250),
    ):
        if not config.auth_required:
            raise HTTPException(
                status_code=409,
                detail="authentication must be enabled for GitHub App installation",
            )
        try:
            principal = review_service.auth.verify_installation_state(state)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        review_service.store.save_installation(
            installation_id, account, principal.tenant_id
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "github.installation.bind",
            str(installation_id), {"account": account},
        )
        return RedirectResponse("/#github", status_code=302)

    @app.get("/metrics", tags=["operations"])
    def prometheus_metrics(_principal: Principal = Depends(read_principal)):
        return PlainTextResponse(
            metrics.prometheus(), media_type="text/plain; version=0.0.4"
        )

    @app.get("/v1/repository-context/status", tags=["repository-context"])
    def repository_context_status(
        repository: str = Query(min_length=3, max_length=250),
        build_index: bool = Query(default=False),
        principal: Principal = Depends(read_principal),
    ):
        return review_service.repository_context_status(
            repository, principal.tenant_id, build_index
        )

    @app.get("/api/dashboard", tags=["console"])
    def dashboard(principal: Principal = Depends(read_principal)):
        return {
            "stats": review_service.store.dashboard_stats(principal.tenant_id),
            "tasks": review_service.store.list_tasks(10, principal.tenant_id),
            "queue": review_service.queue.backend,
            "orchestrator": review_service.reviewer.name,
            "llm": {
                "enabled": bool(review_service.llm_config),
                "provider": review_service.llm_config.get("provider", "local"),
                "model": review_service.llm_config.get("model", ""),
            },
        }

    @app.get("/api/tasks", tags=["console"])
    def list_tasks(
        limit: int = Query(default=50, ge=1, le=500),
        principal: Principal = Depends(read_principal),
    ):
        return {"tasks": review_service.store.list_tasks(limit, principal.tenant_id)}

    @app.get("/api/skills", tags=["console"])
    def list_skills(principal: Principal = Depends(read_principal)):
        return {
            "skills": review_service.list_skills(principal.tenant_id),
            "llm": {
                "enabled": bool(review_service.llm_config),
                "provider": review_service.llm_config.get("provider", "local"),
                "model": review_service.llm_config.get("model", ""),
            },
        }

    @app.get("/api/failures", tags=["console"])
    def list_failures(principal: Principal = Depends(audit_principal)):
        return {"cases": review_service.store.list_failure_cases(
            False, 100, principal.tenant_id
        )}

    @app.get("/api/audit", tags=["console"])
    def list_audit(
        limit: int = Query(default=100, ge=1, le=500),
        principal: Principal = Depends(audit_principal),
    ):
        return {"events": review_service.store.list_audit(principal.tenant_id, limit)}

    @app.get("/api/alerts", tags=["console"])
    def list_alerts(principal: Principal = Depends(read_principal)):
        return {"alerts": review_service.store.list_alerts(principal.tenant_id)}

    @app.get("/api/deployments/llm-review", tags=["releases"])
    def get_deployment(principal: Principal = Depends(read_principal)):
        return {"deployment": review_service.store.get_deployment(
            principal.tenant_id, "llm-review"
        )}

    @app.post("/v1/evaluation/routing-policy", tags=["evaluation", "releases"])
    def evaluate_routing_policy(
        payload: RoutingPolicyEvaluationRequest,
        principal: Principal = Depends(manage_principal),
    ):
        result = review_service.releases.evaluate_candidate(
            payload.baseline, payload.candidate, payload.require_improvement
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "routing-policy.evaluate",
            "llm-review", {
                "decision": result["decision"],
                "passed": result["passed"],
            },
        )
        return result

    @app.post("/v1/deployments/llm-review", status_code=201, tags=["releases"])
    def configure_deployment(
        payload: DeploymentRequest,
        principal: Principal = Depends(manage_principal),
    ):
        config_value = payload.model_dump()
        result = review_service.releases.configure(
            principal.tenant_id, "llm-review", config_value
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "deployment.configure",
            "llm-review", {
                **{
                    key: value for key, value in config_value.items()
                    if key != "offline_evaluation"
                },
                "offline_evaluation_present": bool(
                    config_value.get("offline_evaluation")
                ),
            },
        )
        return result

    @app.get("/api/queue/dead-letters", tags=["operations"])
    def dead_letters(
        limit: int = Query(default=100, ge=1, le=500),
        principal: Principal = Depends(manage_principal),
    ):
        return {"messages": tenant_dead_letters(principal.tenant_id, limit)}

    @app.post("/v1/queue/dead-letters/replay", status_code=202, tags=["operations"])
    def replay_dead_letter(
        payload: DeadLetterReplayRequest,
        principal: Principal = Depends(manage_principal),
    ):
        allowed = any(
            item.get("message_id") == payload.message_id
            for item in tenant_dead_letters(principal.tenant_id, 500)
        )
        if not allowed or not review_service.queue.replay_dead_letter(payload.message_id):
            raise HTTPException(status_code=404, detail="dead letter not found")
        return {"replayed": True}

    @app.get("/v1/evaluation/cases", tags=["evaluation"])
    def evaluation_cases(
        split: Literal["train", "validation", "holdout"] = "validation",
        _principal: Principal = Depends(read_principal),
    ):
        if split == "holdout":
            raise HTTPException(
                status_code=403, detail="holdout cases are not exposed through the API"
            )
        return {"cases": review_service.store.list_evaluation_cases(split, True, 100)}

    @app.post("/v1/evaluation/cases", status_code=201, tags=["evaluation"])
    def add_evaluation_case(
        payload: EvaluationCaseRequest,
        principal: Principal = Depends(manage_principal),
    ):
        result = review_service.evolution.add_evaluation_case(
            payload.name, payload.diff, payload.expected_findings, payload.split, "api"
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "evaluation.case.create",
            payload.name, {"split": payload.split},
        )
        return result

    @app.get("/v1/annotations/cases", tags=["annotations"])
    def annotation_cases(
        status: str = Query(default="", max_length=50),
        split: str = Query(default="", max_length=20),
        limit: int = Query(default=100, ge=1, le=500),
        principal: Principal = Depends(read_principal),
    ):
        if status and status not in {
            "ready", "in_review", "needs_adjudication", "approved", "exported",
        }:
            raise HTTPException(status_code=422, detail="invalid annotation status")
        if split and split not in {"train", "validation", "holdout"}:
            raise HTTPException(status_code=422, detail="invalid annotation split")
        return {"cases": review_service.annotations.list_cases(
            principal.tenant_id, principal, status, split, limit
        )}

    @app.post("/v1/annotations/cases/import", status_code=201, tags=["annotations"])
    def import_annotation_case(
        payload: AnnotationImportRequest,
        principal: Principal = Depends(manage_principal),
    ):
        result = review_service.annotations.import_public_pr(
            principal.tenant_id, principal.username, payload.repository,
            payload.pull_request, payload.license_spdx, payload.license_evidence_url,
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "annotation.case.import",
            result["id"], {
                "repository": result["repository"],
                "pull_request": result["pull_request"],
                "split": result["split"],
                "diff_sha256": result["diff_sha256"],
            },
        )
        return result

    @app.get("/v1/annotations/cases/{case_id}", tags=["annotations"])
    def annotation_case(
        case_id: str = ApiPath(min_length=1, max_length=100),
        principal: Principal = Depends(review_principal),
    ):
        return review_service.annotations.get_case(
            principal.tenant_id, case_id, principal
        )

    @app.post(
        "/v1/annotations/cases/{case_id}/submissions",
        status_code=201,
        tags=["annotations"],
    )
    def submit_annotation(
        payload: AnnotationSubmissionRequest,
        case_id: str = ApiPath(min_length=1, max_length=100),
        principal: Principal = Depends(review_principal),
    ):
        result = review_service.annotations.submit(
            principal.tenant_id, case_id, principal.user_id, principal.username,
            payload.verdict,
            [item.model_dump() for item in payload.findings],
            payload.methodology, payload.evidence_urls,
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "annotation.submission.create",
            case_id, {
                "submission_id": result["submission"]["id"],
                "verdict": payload.verdict,
                "finding_count": len(payload.findings),
                "case_status": result["case_status"],
            },
        )
        return result

    @app.post(
        "/v1/annotations/cases/{case_id}/adjudications",
        status_code=201,
        tags=["annotations"],
    )
    def adjudicate_annotation(
        payload: AnnotationAdjudicationRequest,
        case_id: str = ApiPath(min_length=1, max_length=100),
        principal: Principal = Depends(manage_principal),
    ):
        result = review_service.annotations.adjudicate(
            principal.tenant_id, case_id, principal.user_id, principal.username,
            payload.verdict, [item.model_dump() for item in payload.findings],
            payload.rationale,
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "annotation.adjudication.create",
            case_id, {
                "adjudication_id": result["adjudication"]["id"],
                "verdict": payload.verdict,
                "finding_count": len(payload.findings),
            },
        )
        return result

    @app.get("/v1/annotations/exports", tags=["annotations"])
    def annotation_exports(
        limit: int = Query(default=100, ge=1, le=500),
        principal: Principal = Depends(manage_principal),
    ):
        return {"exports": review_service.store.list_annotation_exports(
            principal.tenant_id, limit
        )}

    @app.post("/v1/annotations/exports", status_code=201, tags=["annotations"])
    def export_annotations(
        payload: AnnotationExportRequest,
        principal: Principal = Depends(manage_principal),
    ):
        result = review_service.annotations.export(
            principal.tenant_id, principal.username, payload.name,
            payload.version, payload.splits, payload.case_ids,
        )
        review_service.store.audit(
            principal.tenant_id, principal.username, "annotation.dataset.export",
            result["id"], {
                "name": result["name"], "version": result["version"],
                "cases": result["manifest"]["cases"],
                "dataset_sha256": result["manifest"]["dataset_sha256"],
            },
        )
        return {
            key: value for key, value in result.items() if key != "dataset"
        } | {"download_url": "/v1/annotations/exports/%s/download" % result["id"]}

    @app.get(
        "/v1/annotations/exports/{export_id}/download",
        tags=["annotations"],
    )
    def download_annotation_export(
        export_id: str = ApiPath(min_length=1, max_length=100),
        principal: Principal = Depends(manage_principal),
    ):
        result = review_service.store.get_annotation_export(
            export_id, principal.tenant_id
        )
        if not result:
            raise HTTPException(status_code=404, detail="annotation export not found")
        body = "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in result["dataset"]
        )
        filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", result["name"]).strip("-")
        safe_version = re.sub(
            r"[^A-Za-z0-9_.-]+", "-", result["version"]
        ).strip("-")
        return Response(
            body, media_type="application/x-ndjson",
            headers={
                "Content-Disposition": "attachment; filename=%s-%s.jsonl"
                % (filename or "codeevo-dataset", safe_version or "dataset"),
                "X-Dataset-SHA256": result["manifest"]["dataset_sha256"],
            },
        )

    @app.get("/v1/evolution/status", tags=["evolution"])
    def evolution_status(_principal: Principal = Depends(read_principal)):
        status = review_service.evolution.status()
        status["provider"] = review_service.llm_config.get("provider", "local")
        status["model"] = review_service.llm_config.get("model", "")
        return status

    @app.get("/v1/evolution/runs", tags=["evolution"])
    def evolution_runs(
        limit: int = Query(default=50, ge=1, le=500),
        _principal: Principal = Depends(read_principal),
    ):
        return {"runs": review_service.store.list_evolution_runs(limit)}

    @app.post("/v1/evolution/auto", status_code=201, tags=["evolution"])
    def auto_evolution(
        payload: EvolutionAutoRequest,
        principal: Principal = Depends(manage_principal),
    ):
        result = review_service.evolution.auto_propose(
            payload.skill_name, principal.tenant_id
        )
        if result["decision"] == "activated":
            review_service.reload_skills()
        review_service.store.audit(
            principal.tenant_id, principal.username, "prompt.evolution.auto",
            payload.skill_name, {"decision": result["decision"]},
        )
        return result

    @app.post("/v1/evolution/propose", status_code=201, tags=["evolution"])
    def propose_evolution(
        payload: EvolutionProposalRequest,
        principal: Principal = Depends(manage_principal),
    ):
        result = review_service.evolution.propose(
            payload.skill_name, payload.prompt, payload.regression_score
        )
        if result["decision"] == "activated":
            review_service.reload_skills()
        review_service.store.audit(
            principal.tenant_id, principal.username, "prompt.evolution.propose",
            payload.skill_name, {"decision": result["decision"]},
        )
        return result

    @app.post(
        "/v1/skills/{skill_name}/versions/{version}/activate",
        tags=["evolution"],
    )
    def activate_prompt_version(
        skill_name: str = ApiPath(pattern=VERSIONED_SKILL_PATTERN),
        version: int = ApiPath(ge=1),
        principal: Principal = Depends(manage_principal),
    ):
        ok = review_service.evolution.rollback(skill_name, version)
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        review_service.reload_skills()
        review_service.store.audit(
            principal.tenant_id, principal.username, "prompt.version.activate",
            skill_name, {"version": version},
        )
        return {"activated": True}

    @app.get("/v1/skill-evolution/status", tags=["skill-evolution"])
    def skill_evolution_status(
        skill_name: str = Query(default="evolved-review", pattern=SKILL_NAME_PATTERN),
        principal: Principal = Depends(manage_principal),
    ):
        return review_service.skill_evolution.status(skill_name, principal.tenant_id)

    @app.get("/v1/skill-evolution/runs", tags=["skill-evolution"])
    def skill_evolution_runs(
        limit: int = Query(default=50, ge=1, le=500),
        principal: Principal = Depends(manage_principal),
    ):
        return {"runs": review_service.store.list_skill_evolution_runs(
            limit, principal.tenant_id
        )}

    @app.get(
        "/v1/skill-evolution/{skill_name}/versions", tags=["skill-evolution"]
    )
    def skill_artifact_versions(
        skill_name: str = ApiPath(pattern=SKILL_NAME_PATTERN),
        principal: Principal = Depends(manage_principal),
    ):
        return {"versions": review_service.store.list_skill_artifact_versions(
            skill_name, principal.tenant_id
        )}

    @app.post("/v1/skill-evolution/auto", status_code=201, tags=["skill-evolution"])
    def auto_skill_evolution(
        payload: SkillEvolutionAutoRequest,
        principal: Principal = Depends(manage_principal),
    ):
        result = review_service.skill_evolution.auto_propose(
            payload.skill_name, principal.tenant_id
        )
        if result["decision"] == "activated":
            review_service.reload_skills()
        review_service.store.audit(
            principal.tenant_id, principal.username, "skill.evolution.auto",
            payload.skill_name,
            {"decision": result["decision"], "run_id": result.get("run_id")},
        )
        return result

    @app.post("/v1/skill-evolution/propose", status_code=201, tags=["skill-evolution"])
    def propose_skill_evolution(
        payload: SkillEvolutionProposalRequest,
        principal: Principal = Depends(manage_principal),
    ):
        result = review_service.skill_evolution.propose(
            payload.skill_name, payload.artifact, principal.tenant_id
        )
        if result["decision"] == "activated":
            review_service.reload_skills()
        review_service.store.audit(
            principal.tenant_id, principal.username, "skill.evolution.propose",
            payload.skill_name,
            {"decision": result["decision"], "run_id": result.get("run_id")},
        )
        return result

    @app.post(
        "/v1/skill-evolution/{skill_name}/versions/{version}/activate",
        tags=["skill-evolution"],
    )
    def activate_skill_artifact(
        skill_name: str = ApiPath(pattern=SKILL_NAME_PATTERN),
        version: int = ApiPath(ge=1),
        principal: Principal = Depends(manage_principal),
    ):
        ok = review_service.skill_evolution.rollback(
            skill_name, version, principal.tenant_id
        )
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        review_service.reload_skills()
        review_service.store.audit(
            principal.tenant_id, principal.username, "skill.evolution.activate",
            skill_name, {"version": version, "activated": True},
        )
        return {"activated": True}

    @app.post("/v1/skills/reload", tags=["skills"])
    def reload_skills(principal: Principal = Depends(manage_principal)):
        skills = review_service.reload_skills()
        review_service.store.audit(
            principal.tenant_id, principal.username, "skills.reload", "registry",
            {"count": len(skills)},
        )
        return {"skills": skills, "note": "New tasks now use the reloaded skill set."}

    return app


def run() -> None:
    import uvicorn

    from .logging_config import configure_logging

    settings = Settings.from_env()
    configure_logging(settings.log_level, settings.log_format)
    app = create_app(settings)
    service = app.state.service
    logger.info(
        "service.starting",
        extra={
            "event": "service.starting",
            "host": settings.host,
            "port": settings.port,
            "persistence": service.store.backend,
            "queue": service.queue.backend,
            "orchestrator": service.reviewer.name,
        },
    )
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        proxy_headers=False,
        log_config=None,
        access_log=False,
    )
