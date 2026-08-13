import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional


_DOTENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_dotenv(paths: Optional[Iterable[str]] = None) -> None:
    """Load local dotenv files without overriding real process environment values.

    The project-root file has priority over ``codeevo/.env``.  This allows the
    latter to remain compatible with existing local setups while keeping the
    conventional root-level ``.env`` as the recommended location.
    """
    package_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(package_dir)
    candidates = list(paths) if paths is not None else [
        os.path.join(project_root, ".env"),
        os.path.join(package_dir, ".env"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                lines = handle.readlines()
        except OSError:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, value = (part.strip() for part in line.split("=", 1))
            if not _DOTENV_KEY.fullmatch(key):
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ.setdefault(key, value)


load_dotenv()


def _int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError("%s must be positive" % name)
    return value


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _non_negative_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError("%s must be non-negative" % name)
    return value


def _optional_float(name: str) -> Optional[float]:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else None


def _csv(name: str) -> tuple:
    return tuple(
        item.strip() for item in os.getenv(name, "").split(",") if item.strip()
    )


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_path: str
    max_diff_bytes: int
    max_steps: int
    timeout_seconds: int
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    github_webhook_secret: str
    github_token: str
    auto_post_review: bool
    database_url: str = ""
    database_auto_migrate: bool = True
    redis_url: str = ""
    trusted_proxy_cidrs: tuple = ()
    log_format: str = "json"
    log_level: str = "INFO"
    repository_root: str = ""
    repository_max_file_bytes: int = 256 * 1024
    repository_max_files: int = 2000
    repository_max_index_bytes: int = 20 * 1024 * 1024
    repository_context_lines: int = 4
    async_workers: int = 2
    agent_max_workers: int = 4
    agent_retries: int = 1
    collaboration_rounds: int = 2
    agent_loop_max_steps: int = 4
    agent_loop_timeout_seconds: int = 45
    context_max_tokens: int = 12000
    context_reserved_tokens: int = 2500
    memory_enabled: bool = True
    memory_recall_limit: int = 6
    memory_working_ttl_seconds: int = 86400
    skills_dir: str = "skills"
    github_app_id: str = ""
    github_app_slug: str = ""
    github_private_key_path: str = ""
    public_base_url: str = "http://127.0.0.1:8080"
    llm_provider: str = "local"
    deepseek_api_key: str = ""
    openrouter_api_key: str = ""
    openrouter_site_url: str = ""
    openrouter_app_name: str = "CodeEvo"
    eval_max_cases: int = 5
    eval_min_cases: int = 3
    eval_min_improvement: float = 0.01
    eval_min_holdout_cases: int = 2
    eval_max_metric_regression: float = 0.0
    eval_max_latency_growth_ratio: float = 0.25
    eval_max_token_growth_ratio: float = 0.20
    eval_max_cost_growth_ratio: float = 0.20
    llm_input_cost_per_million: Optional[float] = None
    llm_output_cost_per_million: Optional[float] = None
    auth_required: bool = False
    auth_secret: str = ""
    bootstrap_admin_username: str = ""
    bootstrap_admin_password: str = ""
    default_tenant_id: str = "default"
    session_ttl_seconds: int = 3600
    login_max_attempts: int = 5
    login_window_seconds: int = 300
    login_lockout_seconds: int = 300
    webhook_max_age_seconds: int = 600
    queue_max_attempts: int = 3
    queue_lease_seconds: int = 60
    skill_timeout_seconds: int = 30
    skill_memory_mb: int = 256
    skill_sandbox: bool = True
    skill_signing_key: str = ""
    skill_container_image: str = ""
    repair_test_command: str = ""
    repair_verify_timeout_seconds: int = 120
    otel_endpoint: str = ""
    otel_service_name: str = "codeevo"
    alert_failure_rate: float = 0.20
    alert_min_samples: int = 10
    alert_window_seconds: int = 900
    alert_webhook_url: str = ""
    alert_smtp_host: str = ""
    alert_email_to: str = ""
    continuous_eval_seconds: int = 0
    guest_demo_enabled: bool = False
    guest_demo_tenant_id: str = "public-demo"
    guest_demo_ttl_seconds: int = 900

    def resolved_llm(self) -> Dict[str, object]:
        """Resolve a named provider to the existing OpenAI-compatible transport."""
        provider = self.llm_provider.strip().lower()
        if provider in {"local", "none"}:
            return {}
        if not provider:
            if self.llm_base_url or self.llm_api_key or self.llm_model:
                provider = "custom"
            else:
                return {}

        if provider == "deepseek":
            api_key = self.deepseek_api_key or self.llm_api_key
            if not api_key:
                raise ValueError("DeepSeek requires CODEEVO_DEEPSEEK_API_KEY")
            return {
                "provider": "deepseek",
                "base_url": self.llm_base_url or "https://api.deepseek.com",
                "api_key": api_key,
                "model": self.llm_model or "deepseek-chat",
                "headers": {},
                "input_cost_per_million": self.llm_input_cost_per_million,
                "output_cost_per_million": self.llm_output_cost_per_million,
            }

        if provider in {"openrouter-deepseek-free", "openrouter_deepseek_free"}:
            api_key = self.openrouter_api_key or self.llm_api_key
            if not api_key:
                raise ValueError("OpenRouter requires CODEEVO_OPENROUTER_API_KEY")
            headers = {}
            if self.openrouter_site_url:
                headers["HTTP-Referer"] = self.openrouter_site_url
            if self.openrouter_app_name:
                headers["X-Title"] = self.openrouter_app_name
            return {
                "provider": "openrouter-deepseek-free",
                "base_url": self.llm_base_url or "https://openrouter.ai/api/v1",
                "api_key": api_key,
                "model": self.llm_model or "deepseek/deepseek-chat-v3-0324:free",
                "headers": headers,
                "input_cost_per_million": self.llm_input_cost_per_million,
                "output_cost_per_million": self.llm_output_cost_per_million,
            }

        if provider == "openrouter-free":
            api_key = self.openrouter_api_key or self.llm_api_key
            if not api_key:
                raise ValueError("OpenRouter requires CODEEVO_OPENROUTER_API_KEY")
            headers = {}
            if self.openrouter_site_url:
                headers["HTTP-Referer"] = self.openrouter_site_url
            if self.openrouter_app_name:
                headers["X-Title"] = self.openrouter_app_name
            return {
                "provider": "openrouter-free",
                "base_url": self.llm_base_url or "https://openrouter.ai/api/v1",
                "api_key": api_key,
                "model": self.llm_model or "openrouter/free",
                "headers": headers,
                "input_cost_per_million": self.llm_input_cost_per_million,
                "output_cost_per_million": self.llm_output_cost_per_million,
            }

        if provider == "custom":
            if not (self.llm_base_url and self.llm_api_key and self.llm_model):
                raise ValueError(
                    "Custom LLM requires CODEEVO_LLM_BASE_URL, "
                    "CODEEVO_LLM_API_KEY and CODEEVO_LLM_MODEL"
                )
            return {
                "provider": "custom",
                "base_url": self.llm_base_url,
                "api_key": self.llm_api_key,
                "model": self.llm_model,
                "headers": {},
                "input_cost_per_million": self.llm_input_cost_per_million,
                "output_cost_per_million": self.llm_output_cost_per_million,
            }
        raise ValueError("unsupported CODEEVO_LLM_PROVIDER: %s" % self.llm_provider)

    def validate_evolution(self) -> None:
        if self.eval_min_cases > self.eval_max_cases:
            raise ValueError("CODEEVO_EVAL_MIN_CASES cannot exceed CODEEVO_EVAL_MAX_CASES")
        if not 0.0 <= self.eval_min_improvement <= 1.0:
            raise ValueError("CODEEVO_EVAL_MIN_IMPROVEMENT must be between 0 and 1")
        if self.eval_min_holdout_cases > self.eval_max_cases:
            raise ValueError("CODEEVO_EVAL_MIN_HOLDOUT_CASES cannot exceed CODEEVO_EVAL_MAX_CASES")
        if not 0.0 <= self.eval_max_metric_regression <= 1.0:
            raise ValueError("CODEEVO_EVAL_MAX_METRIC_REGRESSION must be between 0 and 1")
        for name, value in (
            ("CODEEVO_EVAL_MAX_LATENCY_GROWTH_RATIO", self.eval_max_latency_growth_ratio),
            ("CODEEVO_EVAL_MAX_TOKEN_GROWTH_RATIO", self.eval_max_token_growth_ratio),
            ("CODEEVO_EVAL_MAX_COST_GROWTH_RATIO", self.eval_max_cost_growth_ratio),
        ):
            if value < 0.0:
                raise ValueError("%s cannot be negative" % name)
        for name, value in (
            ("CODEEVO_LLM_INPUT_COST_PER_MILLION", self.llm_input_cost_per_million),
            ("CODEEVO_LLM_OUTPUT_COST_PER_MILLION", self.llm_output_cost_per_million),
        ):
            if value is not None and value < 0.0:
                raise ValueError("%s cannot be negative" % name)
        if bool(self.llm_input_cost_per_million is not None) != bool(
            self.llm_output_cost_per_million is not None
        ):
            raise ValueError(
                "CODEEVO_LLM_INPUT_COST_PER_MILLION and "
                "CODEEVO_LLM_OUTPUT_COST_PER_MILLION must be configured together"
            )
        if self.auth_required and len(self.auth_secret.encode("utf-8")) < 32:
            raise ValueError(
                "CODEEVO_AUTH_SECRET must contain at least 32 bytes when authentication is enabled"
            )
        if self.guest_demo_enabled and not self.auth_required:
            raise ValueError("guest demo mode requires authentication")
        if self.guest_demo_enabled and not self.guest_demo_tenant_id.strip():
            raise ValueError("CODEEVO_GUEST_DEMO_TENANT_ID cannot be empty")
        if bool(self.bootstrap_admin_username) != bool(self.bootstrap_admin_password):
            raise ValueError("bootstrap admin username and password must be configured together")
        if self.login_max_attempts < 1:
            raise ValueError("CODEEVO_LOGIN_MAX_ATTEMPTS must be at least 1")
        if not 0.0 <= self.alert_failure_rate <= 1.0:
            raise ValueError("CODEEVO_ALERT_FAILURE_RATE must be between 0 and 1")
        if self.agent_max_workers < 1:
            raise ValueError("CODEEVO_AGENT_MAX_WORKERS must be at least 1")
        if self.agent_retries < 0:
            raise ValueError("CODEEVO_AGENT_RETRIES cannot be negative")
        if self.collaboration_rounds < 1:
            raise ValueError("CODEEVO_COLLABORATION_ROUNDS must be at least 1")
        if self.agent_loop_max_steps < 1:
            raise ValueError("CODEEVO_AGENT_LOOP_MAX_STEPS must be at least 1")
        if self.context_max_tokens < 512:
            raise ValueError("CODEEVO_CONTEXT_MAX_TOKENS must be at least 512")
        if not 0 <= self.context_reserved_tokens < self.context_max_tokens:
            raise ValueError(
                "CODEEVO_CONTEXT_RESERVED_TOKENS must be smaller than the context budget"
            )
        if self.repository_context_lines > 99:
            raise ValueError("CODEEVO_REPOSITORY_CONTEXT_LINES cannot exceed 99")
        if self.repository_max_files > 10000:
            raise ValueError("CODEEVO_REPOSITORY_MAX_FILES cannot exceed 10000")
        if self.repository_max_index_bytes > 100 * 1024 * 1024:
            raise ValueError(
                "CODEEVO_REPOSITORY_MAX_INDEX_BYTES cannot exceed 104857600"
            )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("CODEEVO_HOST", "127.0.0.1"),
            port=_int("CODEEVO_PORT", 8080),
            db_path=os.getenv("CODEEVO_DB_PATH", "codeevo.db"),
            max_diff_bytes=_int("CODEEVO_MAX_DIFF_BYTES", 1024 * 1024),
            max_steps=_int("CODEEVO_MAX_STEPS", 8),
            timeout_seconds=_int("CODEEVO_TIMEOUT_SECONDS", 120),
            llm_base_url=os.getenv("CODEEVO_LLM_BASE_URL", "").rstrip("/"),
            llm_api_key=os.getenv("CODEEVO_LLM_API_KEY", ""),
            llm_model=os.getenv("CODEEVO_LLM_MODEL", ""),
            llm_input_cost_per_million=_optional_float(
                "CODEEVO_LLM_INPUT_COST_PER_MILLION"
            ),
            llm_output_cost_per_million=_optional_float(
                "CODEEVO_LLM_OUTPUT_COST_PER_MILLION"
            ),
            github_webhook_secret=os.getenv("CODEEVO_GITHUB_WEBHOOK_SECRET", ""),
            github_token=os.getenv("CODEEVO_GITHUB_TOKEN", ""),
            auto_post_review=_bool("CODEEVO_AUTO_POST_REVIEW"),
            database_url=os.getenv("CODEEVO_DATABASE_URL", ""),
            database_auto_migrate=_bool("CODEEVO_DATABASE_AUTO_MIGRATE", True),
            redis_url=os.getenv("CODEEVO_REDIS_URL", ""),
            trusted_proxy_cidrs=_csv("CODEEVO_TRUSTED_PROXY_CIDRS"),
            log_format=os.getenv("CODEEVO_LOG_FORMAT", "json").strip().lower(),
            log_level=os.getenv("CODEEVO_LOG_LEVEL", "INFO").strip().upper(),
            repository_root=os.getenv("CODEEVO_REPOSITORY_ROOT", "").strip(),
            repository_max_file_bytes=_int(
                "CODEEVO_REPOSITORY_MAX_FILE_BYTES", 256 * 1024
            ),
            repository_max_files=_int("CODEEVO_REPOSITORY_MAX_FILES", 2000),
            repository_max_index_bytes=_int(
                "CODEEVO_REPOSITORY_MAX_INDEX_BYTES", 20 * 1024 * 1024
            ),
            repository_context_lines=_int("CODEEVO_REPOSITORY_CONTEXT_LINES", 4),
            async_workers=_int("CODEEVO_ASYNC_WORKERS", 2),
            agent_max_workers=_int("CODEEVO_AGENT_MAX_WORKERS", 4),
            agent_retries=_non_negative_int("CODEEVO_AGENT_RETRIES", 1),
            collaboration_rounds=_int("CODEEVO_COLLABORATION_ROUNDS", 2),
            agent_loop_max_steps=_int("CODEEVO_AGENT_LOOP_MAX_STEPS", 4),
            agent_loop_timeout_seconds=_int("CODEEVO_AGENT_LOOP_TIMEOUT_SECONDS", 45),
            context_max_tokens=_int("CODEEVO_CONTEXT_MAX_TOKENS", 12000),
            context_reserved_tokens=_non_negative_int(
                "CODEEVO_CONTEXT_RESERVED_TOKENS", 2500
            ),
            memory_enabled=_bool("CODEEVO_MEMORY_ENABLED", True),
            memory_recall_limit=_int("CODEEVO_MEMORY_RECALL_LIMIT", 6),
            memory_working_ttl_seconds=_int(
                "CODEEVO_MEMORY_WORKING_TTL_SECONDS", 86400
            ),
            skills_dir=os.getenv("CODEEVO_SKILLS_DIR", "skills"),
            github_app_id=os.getenv("CODEEVO_GITHUB_APP_ID", ""),
            github_app_slug=os.getenv("CODEEVO_GITHUB_APP_SLUG", ""),
            github_private_key_path=os.getenv("CODEEVO_GITHUB_PRIVATE_KEY_PATH", ""),
            public_base_url=os.getenv("CODEEVO_PUBLIC_BASE_URL", "http://127.0.0.1:8080").rstrip("/"),
            llm_provider=os.getenv("CODEEVO_LLM_PROVIDER", "local"),
            deepseek_api_key=os.getenv("CODEEVO_DEEPSEEK_API_KEY", ""),
            openrouter_api_key=os.getenv("CODEEVO_OPENROUTER_API_KEY", ""),
            openrouter_site_url=os.getenv("CODEEVO_OPENROUTER_SITE_URL", ""),
            openrouter_app_name=os.getenv("CODEEVO_OPENROUTER_APP_NAME", "CodeEvo"),
            eval_max_cases=_int("CODEEVO_EVAL_MAX_CASES", 5),
            eval_min_cases=_int("CODEEVO_EVAL_MIN_CASES", 3),
            eval_min_improvement=float(os.getenv("CODEEVO_EVAL_MIN_IMPROVEMENT", "0.01")),
            eval_min_holdout_cases=_non_negative_int("CODEEVO_EVAL_MIN_HOLDOUT_CASES", 2),
            eval_max_metric_regression=float(
                os.getenv("CODEEVO_EVAL_MAX_METRIC_REGRESSION", "0")
            ),
            eval_max_latency_growth_ratio=float(
                os.getenv("CODEEVO_EVAL_MAX_LATENCY_GROWTH_RATIO", "0.25")
            ),
            eval_max_token_growth_ratio=float(
                os.getenv("CODEEVO_EVAL_MAX_TOKEN_GROWTH_RATIO", "0.20")
            ),
            eval_max_cost_growth_ratio=float(
                os.getenv("CODEEVO_EVAL_MAX_COST_GROWTH_RATIO", "0.20")
            ),
            auth_required=_bool("CODEEVO_AUTH_REQUIRED", False),
            auth_secret=os.getenv("CODEEVO_AUTH_SECRET", ""),
            bootstrap_admin_username=os.getenv("CODEEVO_BOOTSTRAP_ADMIN_USERNAME", ""),
            bootstrap_admin_password=os.getenv("CODEEVO_BOOTSTRAP_ADMIN_PASSWORD", ""),
            default_tenant_id=os.getenv("CODEEVO_DEFAULT_TENANT_ID", "default"),
            session_ttl_seconds=_int("CODEEVO_SESSION_TTL_SECONDS", 3600),
            login_max_attempts=_int("CODEEVO_LOGIN_MAX_ATTEMPTS", 5),
            login_window_seconds=_int("CODEEVO_LOGIN_WINDOW_SECONDS", 300),
            login_lockout_seconds=_int("CODEEVO_LOGIN_LOCKOUT_SECONDS", 300),
            webhook_max_age_seconds=_int("CODEEVO_WEBHOOK_MAX_AGE_SECONDS", 600),
            queue_max_attempts=_int("CODEEVO_QUEUE_MAX_ATTEMPTS", 3),
            queue_lease_seconds=_int("CODEEVO_QUEUE_LEASE_SECONDS", 60),
            skill_timeout_seconds=_int("CODEEVO_SKILL_TIMEOUT_SECONDS", 30),
            skill_memory_mb=_int("CODEEVO_SKILL_MEMORY_MB", 256),
            skill_sandbox=_bool("CODEEVO_SKILL_SANDBOX", True),
            skill_signing_key=os.getenv("CODEEVO_SKILL_SIGNING_KEY", ""),
            skill_container_image=os.getenv("CODEEVO_SKILL_CONTAINER_IMAGE", ""),
            repair_test_command=os.getenv("CODEEVO_REPAIR_TEST_COMMAND", ""),
            repair_verify_timeout_seconds=_int("CODEEVO_REPAIR_VERIFY_TIMEOUT_SECONDS", 120),
            otel_endpoint=os.getenv("CODEEVO_OTEL_ENDPOINT", ""),
            otel_service_name=os.getenv("CODEEVO_OTEL_SERVICE_NAME", "codeevo"),
            alert_failure_rate=float(os.getenv("CODEEVO_ALERT_FAILURE_RATE", "0.20")),
            alert_min_samples=_int("CODEEVO_ALERT_MIN_SAMPLES", 10),
            alert_window_seconds=_int("CODEEVO_ALERT_WINDOW_SECONDS", 900),
            alert_webhook_url=os.getenv("CODEEVO_ALERT_WEBHOOK_URL", ""),
            alert_smtp_host=os.getenv("CODEEVO_ALERT_SMTP_HOST", ""),
            alert_email_to=os.getenv("CODEEVO_ALERT_EMAIL_TO", ""),
            continuous_eval_seconds=_non_negative_int(
                "CODEEVO_CONTINUOUS_EVAL_SECONDS", 0
            ),
            guest_demo_enabled=_bool("CODEEVO_GUEST_DEMO_ENABLED", False),
            guest_demo_tenant_id=os.getenv(
                "CODEEVO_GUEST_DEMO_TENANT_ID", "public-demo"
            ).strip(),
            guest_demo_ttl_seconds=_int("CODEEVO_GUEST_DEMO_TTL_SECONDS", 900),
        )
