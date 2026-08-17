"""Typed HTTP contracts for CodeEvo's public API."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorResponse(ApiModel):
    error: str
    request_id: str = ""
    detail: Any = None


class HealthResponse(ApiModel):
    status: str
    reviewer: str
    runtime: str
    queue: str
    llm_provider: str
    llm_model: str
    repository_context_enabled: bool


class ReadinessResponse(ApiModel):
    status: Literal["ok", "unavailable"]
    checks: Dict[str, bool]


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=4096)
    tenant_id: str = Field(default="", max_length=150)


class LoginResponse(ApiModel):
    access_token: str
    token_type: str
    expires_in: int
    tenant_id: str
    role: str


class ReviewRequest(ApiModel):
    repository: str = Field(min_length=1, max_length=250)
    diff: str = Field(min_length=1)
    pull_request: Optional[int] = Field(default=None, ge=1)


class DemoReviewRequest(ApiModel):
    sample: Optional[Literal["injection", "reliability", "clean"]] = None
    diff: Optional[str] = None
    github_pr_url: Optional[str] = Field(default=None, max_length=500)


class ReviewSubmission(ApiModel):
    task_id: str
    state: str
    queue: Optional[str] = None
    report: Optional[Dict[str, Any]] = None


class FeedbackRequest(ApiModel):
    category: Literal["false_positive", "missed_issue", "bad_fix", "accepted"]
    finding: Optional[Dict[str, Any]] = None
    note: str = Field(default="", max_length=2000)


class FixRequest(ApiModel):
    installation_id: Optional[int] = Field(default=None, ge=1)


class DeadLetterReplayRequest(ApiModel):
    message_id: str = Field(min_length=1, max_length=250)


class EvaluationCaseRequest(ApiModel):
    name: str = Field(min_length=1, max_length=250)
    diff: str = Field(min_length=1)
    expected_findings: List[Dict[str, Any]] = Field(default_factory=list)
    split: Literal["train", "validation", "holdout"] = "validation"


class EvolutionAutoRequest(ApiModel):
    skill_name: str = Field(default="llm-review", min_length=1, max_length=100)


class EvolutionProposalRequest(ApiModel):
    skill_name: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=100_000)
    regression_score: Optional[float] = Field(default=None, ge=0, le=1)


class SkillEvolutionAutoRequest(ApiModel):
    skill_name: str = Field(default="evolved-review", min_length=1, max_length=100)


class SkillEvolutionProposalRequest(ApiModel):
    skill_name: str = Field(min_length=1, max_length=100)
    artifact: Dict[str, Any]


class DeploymentRequest(ApiModel):
    stable_version: Optional[int] = Field(default=None, ge=1)
    candidate_version: int = Field(ge=1)
    canary_percent: int = Field(default=0, ge=0, le=100)
    shadow_percent: int = Field(default=0, ge=0, le=100)
    max_error_rate: float = Field(default=0.1, ge=0, le=1)
    max_disagreement_rate: float = Field(default=0.2, ge=0, le=1)
    min_samples: int = Field(default=20, ge=1)
    auto_promote: bool = False
    status: Literal["running", "stable"] = "running"
    offline_evaluation: Optional[Dict[str, Any]] = None


class RoutingPolicyEvaluationRequest(ApiModel):
    baseline: Dict[str, Any]
    candidate: Dict[str, Any]
    require_improvement: bool = False


class AnnotationImportRequest(ApiModel):
    repository: str = Field(min_length=3, max_length=250)
    pull_request: int = Field(ge=1)
    license_spdx: str = Field(min_length=1, max_length=100)
    license_evidence_url: str = Field(min_length=8, max_length=2000)


class AnnotationFinding(ApiModel):
    path: str = Field(min_length=1, max_length=1000)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    cwe: str = Field(min_length=5, max_length=30)
    severity: Literal["low", "medium", "high", "critical"]
    explanation: str = Field(default="", max_length=5000)
    evidence_url: str = Field(default="", max_length=2000)


class AnnotationSubmissionRequest(ApiModel):
    verdict: Literal["risk", "clean"]
    findings: List[AnnotationFinding] = Field(default_factory=list, max_length=200)
    methodology: str = Field(min_length=1, max_length=5000)
    evidence_urls: List[str] = Field(default_factory=list, max_length=100)


class AnnotationAdjudicationRequest(ApiModel):
    verdict: Literal["risk", "clean"]
    findings: List[AnnotationFinding] = Field(default_factory=list, max_length=200)
    rationale: str = Field(min_length=1, max_length=10000)


class AnnotationExportRequest(ApiModel):
    name: str = Field(min_length=1, max_length=250)
    version: str = Field(min_length=1, max_length=100)
    splits: List[Literal["train", "validation", "holdout"]] = Field(
        default_factory=lambda: ["train", "validation"], min_length=1,
    )
    case_ids: List[str] = Field(default_factory=list, max_length=5000)
