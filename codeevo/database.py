"""SQLAlchemy schema, engine construction and Alembic migration helpers."""
import argparse
import os
from pathlib import Path

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)
json_type = JSON().with_variant(JSONB(), "postgresql")
id_type = BigInteger().with_variant(Integer(), "sqlite")
timestamp_type = DateTime(timezone=True)


tasks = Table(
    "tasks",
    metadata,
    Column("id", String, primary_key=True),
    Column("state", String, nullable=False),
    Column("repository", String, nullable=False),
    Column("pull_request", Integer),
    Column("input_json", json_type, nullable=False),
    Column("report_json", json_type),
    Column("error", Text),
    Column("created_at", timestamp_type, nullable=False),
    Column("updated_at", timestamp_type, nullable=False),
    Column("tenant_id", String, nullable=False, server_default=text("'default'")),
    Column("cancel_requested", Boolean, nullable=False, server_default=text("false")),
)

trace_events = Table(
    "trace_events",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("task_id", String, ForeignKey("tasks.id"), nullable=False),
    Column("step", Integer, nullable=False),
    Column("state", String, nullable=False),
    Column("message", Text, nullable=False),
    Column("created_at", timestamp_type, nullable=False),
)

failure_cases = Table(
    "failure_cases",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("task_id", String, nullable=False),
    Column("category", String, nullable=False),
    Column("payload_json", json_type, nullable=False),
    Column("resolved", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", timestamp_type, nullable=False),
)

skill_versions = Table(
    "skill_versions",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("skill_name", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("prompt", Text, nullable=False),
    Column("score", Float, nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("false")),
    Column("parent_version", Integer),
    Column("created_at", timestamp_type, nullable=False),
    UniqueConstraint("skill_name", "version"),
)

installations = Table(
    "installations",
    metadata,
    Column("installation_id", BigInteger, primary_key=True),
    Column("account_login", String, nullable=False),
    Column("created_at", timestamp_type, nullable=False),
    Column("tenant_id", String, nullable=False, server_default=text("'default'")),
)

evaluation_cases = Table(
    "evaluation_cases",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False, unique=True),
    Column("split", String, nullable=False),
    Column("diff", Text, nullable=False),
    Column("expected_json", json_type, nullable=False),
    Column("source", String, nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", timestamp_type, nullable=False),
)

evolution_runs = Table(
    "evolution_runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("skill_name", String, nullable=False),
    Column("candidate_version", Integer, nullable=False),
    Column("baseline_version", Integer),
    Column("decision", String, nullable=False),
    Column("candidate_score", Float, nullable=False),
    Column("baseline_score", Float, nullable=False),
    Column("metrics_json", json_type, nullable=False),
    Column("created_at", timestamp_type, nullable=False),
)

skill_artifact_versions = Table(
    "skill_artifact_versions",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("tenant_id", String, nullable=False, server_default=text("'default'")),
    Column("skill_name", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("artifact_json", json_type, nullable=False),
    Column("artifact_sha256", String, nullable=False),
    Column("score", Float, nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("false")),
    Column("parent_version", Integer),
    Column("created_at", timestamp_type, nullable=False),
    UniqueConstraint("tenant_id", "skill_name", "version"),
)

skill_evolution_runs = Table(
    "skill_evolution_runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("tenant_id", String, nullable=False, server_default=text("'default'")),
    Column("skill_name", String, nullable=False),
    Column("candidate_version", Integer, nullable=False),
    Column("baseline_version", Integer),
    Column("decision", String, nullable=False),
    Column("candidate_score", Float, nullable=False),
    Column("baseline_score", Float, nullable=False),
    Column("metrics_json", json_type, nullable=False),
    Column("created_at", timestamp_type, nullable=False),
)

checkpoints = Table(
    "checkpoints",
    metadata,
    Column("task_id", String, ForeignKey("tasks.id"), primary_key=True),
    Column("node", String, primary_key=True),
    Column("status", String, nullable=False),
    Column("attempt", Integer, nullable=False, server_default=text("1")),
    Column("state_json", json_type, nullable=False),
    Column("error", Text),
    Column("updated_at", timestamp_type, nullable=False),
)

task_payloads = Table(
    "task_payloads",
    metadata,
    Column("task_id", String, ForeignKey("tasks.id"), primary_key=True),
    Column("diff", Text, nullable=False),
    Column("created_at", timestamp_type, nullable=False),
)

agent_messages = Table(
    "agent_messages",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("task_id", String, ForeignKey("tasks.id"), nullable=False),
    Column("sender", String, nullable=False),
    Column("recipient", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("correlation_id", String, nullable=False),
    Column("content_json", json_type, nullable=False),
    Column("created_at", timestamp_type, nullable=False),
)

webhook_deliveries = Table(
    "webhook_deliveries",
    metadata,
    Column("delivery_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("payload_sha256", String, nullable=False),
    Column("task_id", String),
    Column("received_at", timestamp_type, nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("id", String, primary_key=True),
    Column("username", String, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", timestamp_type, nullable=False),
)

memberships = Table(
    "memberships",
    metadata,
    Column("user_id", String, ForeignKey("users.id"), primary_key=True),
    Column("tenant_id", String, primary_key=True),
    Column("role", String, nullable=False),
)

repository_grants = Table(
    "repository_grants",
    metadata,
    Column("tenant_id", String, primary_key=True),
    Column("repository", String, primary_key=True),
    Column("auto_fix", Boolean, nullable=False, server_default=text("false")),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("tenant_id", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("action", String, nullable=False),
    Column("resource", String, nullable=False),
    Column("detail_json", json_type, nullable=False),
    Column("created_at", timestamp_type, nullable=False),
)

deployments = Table(
    "deployments",
    metadata,
    Column("tenant_id", String, primary_key=True),
    Column("skill_name", String, primary_key=True),
    Column("stable_version", Integer),
    Column("candidate_version", Integer),
    Column("canary_percent", Integer, nullable=False, server_default=text("0")),
    Column("shadow_percent", Integer, nullable=False, server_default=text("0")),
    Column("max_error_rate", Float, nullable=False, server_default=text("0.1")),
    Column("max_disagreement_rate", Float, nullable=False, server_default=text("0.2")),
    Column("min_samples", Integer, nullable=False, server_default=text("20")),
    Column("auto_promote", Boolean, nullable=False, server_default=text("false")),
    Column("status", String, nullable=False, server_default=text("'stable'")),
    Column("samples", Integer, nullable=False, server_default=text("0")),
    Column("errors", Integer, nullable=False, server_default=text("0")),
    Column("shadow_samples", Integer, nullable=False, server_default=text("0")),
    Column("disagreements", Integer, nullable=False, server_default=text("0")),
    Column("updated_at", timestamp_type, nullable=False),
)

release_observations = Table(
    "release_observations",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("tenant_id", String, nullable=False),
    Column("skill_name", String, nullable=False),
    Column("task_id", String, nullable=False),
    Column("lane", String, nullable=False),
    Column("primary_json", json_type, nullable=False),
    Column("candidate_json", json_type),
    Column("disagreement", Float, nullable=False),
    Column("candidate_failed", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", timestamp_type, nullable=False),
)
Index(
    "idx_release_observations_lookup",
    release_observations.c.tenant_id,
    release_observations.c.skill_name,
    desc(release_observations.c.created_at),
)

alerts = Table(
    "alerts",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("tenant_id", String, nullable=False),
    Column("alert_key", String, nullable=False),
    Column("severity", String, nullable=False),
    Column("message", Text, nullable=False),
    Column("status", String, nullable=False, server_default=text("'open'")),
    Column("created_at", timestamp_type, nullable=False),
    Column("updated_at", timestamp_type, nullable=False),
    UniqueConstraint("tenant_id", "alert_key", "status"),
)

agent_memories = Table(
    "agent_memories",
    metadata,
    Column("id", String, primary_key=True),
    Column("tenant_id", String, nullable=False),
    Column("repository", String, nullable=False),
    Column("task_id", String, nullable=False, server_default=text("''")),
    Column("agent", String, nullable=False, server_default=text("''")),
    Column("scope", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("content", Text, nullable=False),
    Column("keywords_json", json_type, nullable=False),
    Column("metadata_json", json_type, nullable=False),
    Column("importance", Float, nullable=False, server_default=text("0.5")),
    Column("created_at", timestamp_type, nullable=False),
    Column("expires_at", timestamp_type),
)
Index(
    "idx_agent_memories_lookup",
    agent_memories.c.tenant_id,
    agent_memories.c.repository,
    agent_memories.c.scope,
    agent_memories.c.created_at,
)

annotation_cases = Table(
    "annotation_cases",
    metadata,
    Column("id", String, primary_key=True),
    Column("tenant_id", String, nullable=False),
    Column("repository", String, nullable=False),
    Column("pull_request", Integer, nullable=False),
    Column("split", String, nullable=False),
    Column("status", String, nullable=False),
    Column("source_json", json_type, nullable=False),
    Column("diff", Text, nullable=False),
    Column("diff_sha256", String, nullable=False),
    Column("required_reviewers", Integer, nullable=False, server_default=text("2")),
    Column("created_by", String, nullable=False),
    Column("created_at", timestamp_type, nullable=False),
    Column("updated_at", timestamp_type, nullable=False),
    Column("exported_at", timestamp_type),
    UniqueConstraint("tenant_id", "repository", "pull_request"),
)
Index(
    "idx_annotation_cases_queue",
    annotation_cases.c.tenant_id,
    annotation_cases.c.status,
    annotation_cases.c.split,
    annotation_cases.c.created_at,
)

annotation_submissions = Table(
    "annotation_submissions",
    metadata,
    Column("id", String, primary_key=True),
    Column("case_id", String, ForeignKey("annotation_cases.id"), nullable=False),
    Column("tenant_id", String, nullable=False),
    Column("annotator_id", String, nullable=False),
    Column("annotator", String, nullable=False),
    Column("verdict", String, nullable=False),
    Column("findings_json", json_type, nullable=False),
    Column("methodology", Text, nullable=False),
    Column("evidence_urls_json", json_type, nullable=False),
    Column("revision", Integer, nullable=False, server_default=text("1")),
    Column("submitted_at", timestamp_type, nullable=False),
    UniqueConstraint("case_id", "annotator_id"),
)
Index(
    "idx_annotation_submissions_case",
    annotation_submissions.c.tenant_id,
    annotation_submissions.c.case_id,
    annotation_submissions.c.submitted_at,
)

annotation_adjudications = Table(
    "annotation_adjudications",
    metadata,
    Column("id", String, primary_key=True),
    Column("case_id", String, ForeignKey("annotation_cases.id"), nullable=False, unique=True),
    Column("tenant_id", String, nullable=False),
    Column("adjudicator_id", String, nullable=False),
    Column("adjudicator", String, nullable=False),
    Column("verdict", String, nullable=False),
    Column("findings_json", json_type, nullable=False),
    Column("rationale", Text, nullable=False),
    Column("created_at", timestamp_type, nullable=False),
)

annotation_exports = Table(
    "annotation_exports",
    metadata,
    Column("id", String, primary_key=True),
    Column("tenant_id", String, nullable=False),
    Column("name", String, nullable=False),
    Column("version", String, nullable=False),
    Column("manifest_json", json_type, nullable=False),
    Column("dataset_json", json_type, nullable=False),
    Column("created_by", String, nullable=False),
    Column("created_at", timestamp_type, nullable=False),
    UniqueConstraint("tenant_id", "name", "version"),
)


def normalize_database_url(url: str) -> str:
    """Select psycopg v3 explicitly for conventional PostgreSQL URLs."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def create_database_engine(url: str, **options):
    defaults = {"pool_pre_ping": True}
    if not url.startswith("sqlite"):
        defaults.update({"pool_recycle": 1800})
    defaults.update(options)
    return create_engine(normalize_database_url(url), **defaults)


def upgrade_database(url: str, revision: str = "head") -> None:
    """Upgrade a database using migrations shipped inside the Python package."""
    from alembic import command
    from alembic.config import Config

    migration_root = Path(__file__).resolve().parent / "migrations"
    config = Config()
    config.set_main_option("script_location", str(migration_root))
    config.set_main_option("sqlalchemy.url", normalize_database_url(url).replace("%", "%%"))
    command.upgrade(config, revision)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upgrade the CodeEvo database schema")
    parser.add_argument("revision", nargs="?", default="head")
    parser.add_argument("--database-url", default="")
    args = parser.parse_args()
    url = args.database_url or os.getenv("CODEEVO_DATABASE_URL", "")
    if not url:
        parser.error("set CODEEVO_DATABASE_URL or pass --database-url")
    upgrade_database(url, args.revision)
