"""Persistence boundary and backend selection for CodeEvo services."""
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from .models import ReviewReport, TraceEvent
from .postgres_store import PostgresTaskStore
from .store import TaskStore


@runtime_checkable
class TaskRepository(Protocol):
    """Core contract shared by local and production persistence backends."""

    backend: str

    def create(
        self,
        task_id: str,
        repository: str,
        pull_request: Optional[int],
        payload: Dict[str, Any],
        tenant_id: str = "default",
    ) -> None:
        ...

    def transition(self, task_id: str, event: TraceEvent) -> None:
        ...

    def succeed(
        self, task_id: str, report: ReviewReport, event: TraceEvent
    ) -> None:
        ...

    def fail(self, task_id: str, error: str, event: TraceEvent) -> None:
        ...

    def get(
        self, task_id: str, tenant_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        ...

    def list_tasks(
        self, limit: int = 50, tenant_id: Optional[str] = None
    ) -> list:
        ...


def create_repository(
    database_url: str,
    sqlite_path: str,
    auto_migrate: bool = True,
) -> TaskRepository:
    """Select a repository explicitly; invalid production URLs fail closed."""
    if not database_url:
        return TaskStore(sqlite_path)
    if database_url.startswith(
        ("postgres://", "postgresql://", "postgresql+psycopg://")
    ):
        return PostgresTaskStore(database_url, auto_migrate=auto_migrate)
    raise ValueError(
        "CODEEVO_DATABASE_URL must be a PostgreSQL URL; "
        "leave it empty to use CODEEVO_DB_PATH"
    )
