"""PostgreSQL repository using SQLAlchemy pooling and psycopg v3 operations."""
import hashlib
import json
from contextlib import contextmanager
from typing import Any, Dict, Optional

from .database import create_database_engine, upgrade_database
from .models import ReviewReport, TaskState, TraceEvent
from .store import utc_now


class PostgresTaskStore:
    backend = "postgresql-sqlalchemy"

    def __init__(self, url: str, auto_migrate: bool = True):
        try:
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL mode requires: pip install psycopg[binary]") from exc
        self.url = url
        self._row_factory = dict_row
        # SQLAlchemy must initialize psycopg with its default tuple row factory.
        # A connection-wide dict_row makes dialect probes such as SELECT version()
        # yield the column name ("version") instead of the version value.
        self.engine = create_database_engine(url, connect_args={"connect_timeout": 3})
        if auto_migrate:
            upgrade_database(url)

    @contextmanager
    def _connect(self):
        connection = self.engine.raw_connection()
        driver_connection = connection.driver_connection
        original_row_factory = driver_connection.row_factory
        try:
            driver_connection.row_factory = self._row_factory
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            driver_connection.row_factory = original_row_factory
            connection.close()

    def close(self) -> None:
        self.engine.dispose()

    def ping(self) -> bool:
        """Verify that a pooled PostgreSQL connection is usable."""
        with self.engine.connect() as connection:
            return connection.exec_driver_sql("SELECT 1").scalar_one() == 1

    def create(
        self, task_id: str, repository: str, pull_request: Optional[int],
        payload: Dict[str, Any], tenant_id: str = "default",
    ) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tasks(id,state,repository,pull_request,input_json,report_json,error,"
                "created_at,updated_at,tenant_id,cancel_requested) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,NULL,NULL,%s,%s,%s,FALSE)",
                (task_id, TaskState.PENDING.value, repository, pull_request,
                 json.dumps(payload), now, now, tenant_id),
            )

    def transition(self, task_id: str, event: TraceEvent) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE tasks SET state=%s,updated_at=%s WHERE id=%s", (event.state.value, event.created_at, task_id))
            conn.execute(
                "INSERT INTO trace_events(task_id,step,state,message,created_at) VALUES (%s,%s,%s,%s,%s)",
                (task_id, event.step, event.state.value, event.message, event.created_at),
            )

    def succeed(self, task_id: str, report: ReviewReport, event: TraceEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET state=%s,report_json=%s::jsonb,updated_at=%s WHERE id=%s",
                (TaskState.SUCCESS.value, json.dumps(report.to_dict(), ensure_ascii=False), event.created_at, task_id),
            )
            conn.execute(
                "INSERT INTO trace_events(task_id,step,state,message,created_at) VALUES (%s,%s,%s,%s,%s)",
                (task_id, event.step, event.state.value, event.message, event.created_at),
            )

    def fail(self, task_id: str, error: str, event: TraceEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET state=%s,error=%s,updated_at=%s WHERE id=%s",
                (TaskState.FAILED.value, error[:2000], event.created_at, task_id),
            )
            conn.execute(
                "INSERT INTO trace_events(task_id,step,state,message,created_at) VALUES (%s,%s,%s,%s,%s)",
                (task_id, event.step, event.state.value, event.message, event.created_at),
            )

    def get(self, task_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            query = "SELECT * FROM tasks WHERE id=%s"
            params = [task_id]
            if tenant_id is not None:
                query += " AND tenant_id=%s"
                params.append(tenant_id)
            row = conn.execute(query, params).fetchone()
            if not row:
                return None
            events = conn.execute(
                "SELECT step,state,message,created_at FROM trace_events WHERE task_id=%s ORDER BY id", (task_id,)
            ).fetchall()
            messages = conn.execute(
                "SELECT sender,recipient,kind,correlation_id,content_json,created_at "
                "FROM agent_messages WHERE task_id=%s ORDER BY id", (task_id,)
            ).fetchall()
        value = dict(row)
        value["input"] = value.pop("input_json")
        value["report"] = value.pop("report_json")
        value["trace"] = [dict(item) for item in events]
        value["collaboration"] = []
        for message in messages:
            item = dict(message)
            item["content"] = item.pop("content_json")
            item["created_at"] = item["created_at"].isoformat()
            value["collaboration"].append(item)
        for key in ("created_at", "updated_at"):
            value[key] = value[key].isoformat()
        for item in value["trace"]:
            item["created_at"] = item["created_at"].isoformat()
        return value

    def record_agent_message(self, task_id: str, message: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO agent_messages(task_id,sender,recipient,kind,correlation_id,"
                "content_json,created_at) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)",
                (task_id, message["sender"], message["recipient"], message["kind"],
                 message.get("correlation_id", ""),
                 json.dumps(message.get("content", {}), ensure_ascii=False), utc_now()),
            )

    def save_agent_memory(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO agent_memories(id,tenant_id,repository,task_id,agent,scope,kind,"
                "content,keywords_json,metadata_json,importance,created_at,expires_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s) "
                "ON CONFLICT(id) DO UPDATE SET "
                "importance=GREATEST(agent_memories.importance,EXCLUDED.importance),"
                "expires_at=EXCLUDED.expires_at RETURNING *",
                (
                    memory["id"], memory["tenant_id"], memory["repository"],
                    memory.get("task_id", ""), memory.get("agent", ""), memory["scope"],
                    memory["kind"], memory["content"],
                    json.dumps(memory.get("keywords", []), ensure_ascii=False),
                    json.dumps(memory.get("metadata", {}), ensure_ascii=False),
                    float(memory.get("importance", 0.5)), memory["created_at"],
                    memory.get("expires_at"),
                ),
            ).fetchone()
        return self._memory_from_row(row)

    def list_agent_memories(
        self, tenant_id: str, repository: str, scopes: tuple,
        limit: int = 100,
    ) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_memories WHERE tenant_id=%s AND repository=%s "
                "AND scope=ANY(%s) AND (expires_at IS NULL OR expires_at>%s) "
                "ORDER BY importance DESC,created_at DESC LIMIT %s",
                (
                    tenant_id, repository, list(scopes), utc_now(),
                    max(1, min(limit, 500)),
                ),
            ).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def delete_agent_memories(self, task_id: str = "", scope: str = "") -> int:
        clauses = []
        params = []
        if task_id:
            clauses.append("task_id=%s")
            params.append(task_id)
        if scope:
            clauses.append("scope=%s")
            params.append(scope)
        if not clauses:
            raise ValueError("memory deletion requires task_id or scope")
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM agent_memories WHERE " + " AND ".join(clauses), params
            )
            return cursor.rowcount

    def purge_expired_agent_memories(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM agent_memories WHERE expires_at IS NOT NULL AND expires_at<=%s",
                (utc_now(),),
            )
            return cursor.rowcount

    @staticmethod
    def _memory_from_row(row) -> Dict[str, Any]:
        value = dict(row)
        value["keywords"] = value.pop("keywords_json")
        value["metadata"] = value.pop("metadata_json")
        for key in ("created_at", "expires_at"):
            if value.get(key) is not None:
                value[key] = value[key].isoformat()
        return value

    def list_tasks(self, limit: int = 50, tenant_id: Optional[str] = None) -> list:
        with self._connect() as conn:
            where = " WHERE tenant_id=%s" if tenant_id is not None else ""
            params = ([tenant_id] if tenant_id is not None else []) + [max(1, min(limit, 200))]
            rows = conn.execute(
                "SELECT id,state,repository,pull_request,error,created_at,updated_at,tenant_id "
                "FROM tasks" + where + " ORDER BY created_at DESC LIMIT %s", params
            ).fetchall()
        values = [dict(row) for row in rows]
        for value in values:
            value["created_at"] = value["created_at"].isoformat()
            value["updated_at"] = value["updated_at"].isoformat()
        return values

    def record_failure_case(self, task_id: str, category: str, payload: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO failure_cases(task_id,category,payload_json,created_at) VALUES (%s,%s,%s::jsonb,%s)",
                (task_id, category, json.dumps(payload, ensure_ascii=False), utc_now()),
            )

    def list_failure_cases(
        self, unresolved_only: bool = False, limit: int = 100,
        tenant_id: Optional[str] = None,
    ) -> list:
        joins = " f"
        clauses = []
        params = []
        if tenant_id is not None:
            joins += " JOIN tasks t ON t.id=f.task_id"
            clauses.append("t.tenant_id=%s")
            params.append(tenant_id)
        if unresolved_only:
            clauses.append("f.resolved=FALSE")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT f.* FROM failure_cases" + joins + where
                + " ORDER BY f.id DESC LIMIT %s", params
            ).fetchall()
        values = [dict(row) for row in rows]
        for value in values:
            value["payload"] = value.pop("payload_json")
            value["created_at"] = value["created_at"].isoformat()
        return values

    def list_task_failure_cases(
        self, task_id: str, tenant_id: Optional[str] = None,
    ) -> list:
        joins = " f"
        clauses = ["f.task_id=%s"]
        params = [task_id]
        if tenant_id is not None:
            joins += " JOIN tasks t ON t.id=f.task_id"
            clauses.append("t.tenant_id=%s")
            params.append(tenant_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT f.* FROM failure_cases" + joins
                + " WHERE " + " AND ".join(clauses)
                + " ORDER BY f.id DESC",
                params,
            ).fetchall()
        values = [dict(row) for row in rows]
        for value in values:
            value["payload"] = value.pop("payload_json")
            value["created_at"] = value["created_at"].isoformat()
        return values

    def resolve_failure_cases(self, case_ids: list) -> None:
        ids = [int(value) for value in case_ids]
        if not ids:
            return
        with self._connect() as conn:
            conn.execute("UPDATE failure_cases SET resolved=TRUE WHERE id=ANY(%s)", (ids,))

    def save_evaluation_case(
        self, name: str, split: str, diff: str, expected: list,
        source: str = "manual", active: bool = True,
    ) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO evaluation_cases(name,split,diff,expected_json,source,active,created_at) "
                "VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s) ON CONFLICT(name) DO NOTHING RETURNING *",
                (name, split, diff, json.dumps(expected, ensure_ascii=False), source, active, utc_now()),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM evaluation_cases WHERE name=%s", (name,)
                ).fetchone()
                if (
                    row["split"] != split
                    or row["diff"] != diff
                    or row["expected_json"] != expected
                ):
                    raise ValueError(
                        "evaluation case names are immutable; use a new name for revised content"
                    )
        value = dict(row)
        value["expected"] = value.pop("expected_json")
        value["created_at"] = value["created_at"].isoformat()
        return value

    def list_evaluation_cases(
        self, split: Optional[str] = None, active_only: bool = True, limit: int = 100,
    ) -> list:
        clauses = []
        params = []
        if split:
            clauses.append("split=%s")
            params.append(split)
        if active_only:
            clauses.append("active=TRUE")
        query = "SELECT * FROM evaluation_cases"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id LIMIT %s"
        params.append(max(1, min(limit, 500)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        values = [dict(row) for row in rows]
        for value in values:
            value["expected"] = value.pop("expected_json")
            value["created_at"] = value["created_at"].isoformat()
        return values

    def save_evolution_run(self, run: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evolution_runs(id,skill_name,candidate_version,baseline_version,decision,"
                "candidate_score,baseline_score,metrics_json,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
                (
                    run["id"], run["skill_name"], run["candidate_version"], run.get("baseline_version"),
                    run["decision"], run["candidate_score"], run["baseline_score"],
                    json.dumps(run["metrics"], ensure_ascii=False), run["created_at"],
                ),
            )
        return run

    def list_evolution_runs(self, limit: int = 50) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evolution_runs ORDER BY created_at DESC LIMIT %s",
                (max(1, min(limit, 200)),),
            ).fetchall()
        values = [dict(row) for row in rows]
        for value in values:
            value["metrics"] = value.pop("metrics_json")
            value["created_at"] = value["created_at"].isoformat()
        return values

    def get_active_skill_version(self, skill_name: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_versions WHERE skill_name=%s AND active=TRUE ORDER BY version DESC LIMIT 1",
                (skill_name,),
            ).fetchone()
        return dict(row) if row else None

    def save_skill_version(self, skill_name: str, prompt: str, score: float, activate: bool = False) -> Dict[str, Any]:
        active = self.get_active_skill_version(skill_name)
        with self._connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (skill_name,))
            row = conn.execute(
                "SELECT COALESCE(MAX(version),0) AS version FROM skill_versions WHERE skill_name=%s",
                (skill_name,),
            ).fetchone()
            version = int(row["version"]) + 1
            if activate:
                conn.execute("UPDATE skill_versions SET active=FALSE WHERE skill_name=%s", (skill_name,))
            conn.execute(
                "INSERT INTO skill_versions(skill_name,version,prompt,score,active,parent_version,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (skill_name, version, prompt, score, activate, active["version"] if active else None, utc_now()),
            )
        return {"skill_name": skill_name, "version": version, "score": score, "active": activate}

    def list_skill_versions(self, skill_name: str) -> list:
        with self._connect() as conn:
            return list(conn.execute("SELECT * FROM skill_versions WHERE skill_name=%s ORDER BY version DESC", (skill_name,)).fetchall())

    def activate_skill_version(self, skill_name: str, version: int) -> bool:
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM skill_versions WHERE skill_name=%s AND version=%s", (skill_name, version)).fetchone()
            if not exists:
                return False
            conn.execute("UPDATE skill_versions SET active=FALSE WHERE skill_name=%s", (skill_name,))
            conn.execute("UPDATE skill_versions SET active=TRUE WHERE skill_name=%s AND version=%s", (skill_name, version))
        return True

    def save_skill_artifact(
        self, skill_name: str, artifact: Dict[str, Any], score: float,
        activate: bool = False, tenant_id: str = "default",
    ) -> Dict[str, Any]:
        artifact_json = json.dumps(
            artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        artifact_sha256 = hashlib.sha256(artifact_json.encode("utf-8")).hexdigest()
        active = self.get_active_skill_artifact(skill_name, tenant_id)
        with self._connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("artifact:" + skill_name,))
            row = conn.execute(
                "SELECT COALESCE(MAX(version),0) AS version FROM skill_artifact_versions "
                "WHERE tenant_id=%s AND skill_name=%s", (tenant_id, skill_name),
            ).fetchone()
            version = int(row["version"]) + 1
            if activate:
                conn.execute(
                    "UPDATE skill_artifact_versions SET active=FALSE WHERE tenant_id=%s AND skill_name=%s",
                    (tenant_id, skill_name),
                )
            created_at = utc_now()
            conn.execute(
                "INSERT INTO skill_artifact_versions(tenant_id,skill_name,version,artifact_json,"
                "artifact_sha256,score,active,parent_version,created_at) "
                "VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)",
                (tenant_id, skill_name, version, artifact_json, artifact_sha256, float(score), activate,
                 active["version"] if active else None, created_at),
            )
        return {
            "tenant_id": tenant_id, "skill_name": skill_name, "version": version, "score": float(score),
            "active": activate, "parent_version": active["version"] if active else None,
            "artifact_sha256": artifact_sha256, "created_at": created_at,
        }

    @staticmethod
    def _decode_skill_artifact(row) -> Dict[str, Any]:
        value = dict(row)
        value["artifact"] = value.pop("artifact_json")
        value["active"] = bool(value["active"])
        if hasattr(value.get("created_at"), "isoformat"):
            value["created_at"] = value["created_at"].isoformat()
        return value

    def get_active_skill_artifact(
        self, skill_name: str, tenant_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_artifact_versions WHERE tenant_id=%s AND skill_name=%s "
                "AND active=TRUE ORDER BY version DESC LIMIT 1", (tenant_id, skill_name),
            ).fetchone()
        return self._decode_skill_artifact(row) if row else None

    def list_active_skill_artifacts(self, tenant_id: str = "default") -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_artifact_versions WHERE tenant_id=%s AND active=TRUE "
                "ORDER BY skill_name", (tenant_id,)
            ).fetchall()
        return [self._decode_skill_artifact(row) for row in rows]

    def list_skill_artifact_versions(
        self, skill_name: str, tenant_id: str = "default",
    ) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_artifact_versions WHERE tenant_id=%s AND skill_name=%s "
                "ORDER BY version DESC", (tenant_id, skill_name),
            ).fetchall()
        return [self._decode_skill_artifact(row) for row in rows]

    def activate_skill_artifact(
        self, skill_name: str, version: int, tenant_id: str = "default",
    ) -> bool:
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM skill_artifact_versions v WHERE v.tenant_id=%s "
                "AND v.skill_name=%s AND v.version=%s AND (v.active=TRUE OR EXISTS ("
                "SELECT 1 FROM skill_evolution_runs r WHERE r.tenant_id=v.tenant_id "
                "AND r.skill_name=v.skill_name AND r.candidate_version=v.version "
                "AND r.decision='activated'))",
                (tenant_id, skill_name, version),
            ).fetchone()
            if not exists:
                return False
            conn.execute(
                "UPDATE skill_artifact_versions SET active=FALSE WHERE tenant_id=%s AND skill_name=%s",
                (tenant_id, skill_name),
            )
            conn.execute(
                "UPDATE skill_artifact_versions SET active=TRUE WHERE tenant_id=%s AND skill_name=%s "
                "AND version=%s", (tenant_id, skill_name, version),
            )
        return True

    def save_skill_evolution_run(self, run: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_evolution_runs(id,tenant_id,skill_name,candidate_version,baseline_version,"
                "decision,candidate_score,baseline_score,metrics_json,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
                (run["id"], run.get("tenant_id", "default"), run["skill_name"], run["candidate_version"],
                 run.get("baseline_version"), run["decision"], run["candidate_score"],
                 run["baseline_score"], json.dumps(run["metrics"], ensure_ascii=False),
                 run["created_at"]),
            )
        return run

    def list_skill_evolution_runs(
        self, limit: int = 50, tenant_id: Optional[str] = None,
    ) -> list:
        with self._connect() as conn:
            if tenant_id is None:
                rows = conn.execute(
                    "SELECT * FROM skill_evolution_runs ORDER BY created_at DESC LIMIT %s",
                    (max(1, min(limit, 200)),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM skill_evolution_runs WHERE tenant_id=%s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (tenant_id, max(1, min(limit, 200))),
                ).fetchall()
        values = [dict(row) for row in rows]
        for value in values:
            value["metrics"] = value.pop("metrics_json")
            value["created_at"] = value["created_at"].isoformat()
        return values

    def save_task_payload(self, task_id: str, diff: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO task_payloads(task_id,diff,created_at) VALUES (%s,%s,%s) "
                "ON CONFLICT(task_id) DO UPDATE SET diff=EXCLUDED.diff,created_at=EXCLUDED.created_at",
                (task_id, diff, utc_now()),
            )

    def update_task_input(self, task_id: str, updates: Dict[str, Any]) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT input_json FROM tasks WHERE id=%s", (task_id,)
            ).fetchone()
            if not row:
                raise ValueError("task not found")
            value = dict(row["input_json"])
            value.update(updates)
            conn.execute(
                "UPDATE tasks SET input_json=%s::jsonb,updated_at=%s WHERE id=%s",
                (json.dumps(value, ensure_ascii=False), utc_now(), task_id),
            )

    def get_task_payload(self, task_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT diff FROM task_payloads WHERE task_id=%s", (task_id,)).fetchone()
        return row["diff"] if row else None

    def save_checkpoint(
        self, task_id: str, node: str, state: Dict[str, Any], status: str = "completed",
        attempt: int = 1, error: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO checkpoints(task_id,node,status,attempt,state_json,error,updated_at) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT(task_id,node) DO UPDATE SET "
                "status=EXCLUDED.status,attempt=EXCLUDED.attempt,state_json=EXCLUDED.state_json,"
                "error=EXCLUDED.error,updated_at=EXCLUDED.updated_at",
                (task_id, node, status, attempt, json.dumps(state, ensure_ascii=False),
                 error[:2000] or None, utc_now()),
            )

    def load_checkpoints(self, task_id: str) -> Dict[str, Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT node,status,attempt,state_json,error,updated_at FROM checkpoints "
                "WHERE task_id=%s ORDER BY updated_at", (task_id,)
            ).fetchall()
        result = {}
        for row in rows:
            item = dict(row)
            item["state"] = item.pop("state_json")
            item["updated_at"] = item["updated_at"].isoformat()
            result[item.pop("node")] = item
        return result

    def request_cancel(self, task_id: str, tenant_id: Optional[str] = None) -> bool:
        query = "UPDATE tasks SET cancel_requested=TRUE,updated_at=%s WHERE id=%s"
        params = [utc_now(), task_id]
        if tenant_id is not None:
            query += " AND tenant_id=%s"
            params.append(tenant_id)
        with self._connect() as conn:
            cursor = conn.execute(query, params)
            return cursor.rowcount > 0

    def is_cancelled(self, task_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM tasks WHERE id=%s", (task_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def cancel(self, task_id: str, event: TraceEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET state=%s,updated_at=%s WHERE id=%s",
                (TaskState.CANCELLED.value, event.created_at, task_id),
            )
            conn.execute(
                "INSERT INTO trace_events(task_id,step,state,message,created_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (task_id, event.step, event.state.value, event.message, event.created_at),
            )

    def claim_webhook(
        self, delivery_id: str, tenant_id: str, event_type: str, payload_sha256: str,
    ) -> bool:
        if not delivery_id:
            raise ValueError("X-GitHub-Delivery is required")
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO webhook_deliveries"
                "(delivery_id,tenant_id,event_type,payload_sha256,received_at) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(delivery_id) DO NOTHING RETURNING delivery_id",
                (delivery_id, tenant_id, event_type, payload_sha256, utc_now()),
            ).fetchone()
            if row:
                return True
            existing = conn.execute(
                "SELECT payload_sha256 FROM webhook_deliveries WHERE delivery_id=%s",
                (delivery_id,),
            ).fetchone()
            if existing and existing["payload_sha256"] != payload_sha256:
                raise ValueError("delivery id was already used with a different payload")
            return False

    def complete_webhook(self, delivery_id: str, task_id: Optional[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE webhook_deliveries SET task_id=%s WHERE delivery_id=%s",
                (task_id, delivery_id),
            )

    def get_webhook(self, delivery_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM webhook_deliveries WHERE delivery_id=%s", (delivery_id,)
            ).fetchone()
        return dict(row) if row else None

    def create_user(
        self, user_id: str, username: str, password_hash: str,
        tenant_id: str, role: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,created_at) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT(username) DO NOTHING",
                (user_id, username, password_hash, utc_now()),
            )
            row = conn.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()
            conn.execute(
                "INSERT INTO memberships(user_id,tenant_id,role) VALUES (%s,%s,%s) "
                "ON CONFLICT(user_id,tenant_id) DO UPDATE SET role=EXCLUDED.role",
                (row["id"], tenant_id, role),
            )

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id,username,password_hash,active FROM users WHERE username=%s",
                (username,),
            ).fetchone()
            if not row:
                return None
            memberships = conn.execute(
                "SELECT tenant_id,role FROM memberships WHERE user_id=%s", (row["id"],)
            ).fetchall()
        value = dict(row)
        value["memberships"] = [dict(item) for item in memberships]
        return value

    def grant_repository(self, tenant_id: str, repository: str, auto_fix: bool = False) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO repository_grants(tenant_id,repository,auto_fix) VALUES (%s,%s,%s) "
                "ON CONFLICT(tenant_id,repository) DO UPDATE SET auto_fix=EXCLUDED.auto_fix",
                (tenant_id, repository, auto_fix),
            )

    def repository_allowed(
        self, tenant_id: str, repository: str, require_auto_fix: bool = False,
    ) -> bool:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM repository_grants WHERE tenant_id=%s", (tenant_id,)
            ).fetchone()["n"]
            row = conn.execute(
                "SELECT auto_fix FROM repository_grants WHERE tenant_id=%s AND repository=%s",
                (tenant_id, repository),
            ).fetchone()
        return False if total == 0 else bool(
            row and (not require_auto_fix or row["auto_fix"])
        )

    def audit(
        self, tenant_id: str, actor: str, action: str, resource: str,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_log(tenant_id,actor,action,resource,detail_json,created_at) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s)",
                (tenant_id, actor, action, resource,
                 json.dumps(detail or {}, ensure_ascii=False), utc_now()),
            )

    def list_audit(self, tenant_id: str, limit: int = 100) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT actor,action,resource,detail_json,created_at FROM audit_log "
                "WHERE tenant_id=%s ORDER BY id DESC LIMIT %s",
                (tenant_id, max(1, min(limit, 500))),
            ).fetchall()
        return [{**dict(row), "detail": row["detail_json"],
                 "created_at": row["created_at"].isoformat()} for row in rows]

    def save_deployment(self, tenant_id: str, skill_name: str, config: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO deployments(tenant_id,skill_name,stable_version,candidate_version,"
                "canary_percent,shadow_percent,max_error_rate,min_samples,status,samples,errors,"
                "max_disagreement_rate,auto_promote,shadow_samples,disagreements,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,%s,%s,0,0,%s) "
                "ON CONFLICT(tenant_id,skill_name) DO UPDATE SET stable_version=EXCLUDED.stable_version,"
                "candidate_version=EXCLUDED.candidate_version,canary_percent=EXCLUDED.canary_percent,"
                "shadow_percent=EXCLUDED.shadow_percent,max_error_rate=EXCLUDED.max_error_rate,"
                "min_samples=EXCLUDED.min_samples,status=EXCLUDED.status,samples=0,errors=0,"
                "max_disagreement_rate=EXCLUDED.max_disagreement_rate,"
                "auto_promote=EXCLUDED.auto_promote,shadow_samples=0,disagreements=0,"
                "updated_at=EXCLUDED.updated_at",
                (tenant_id, skill_name, config.get("stable_version"), config.get("candidate_version"),
                 int(config.get("canary_percent", 0)), int(config.get("shadow_percent", 0)),
                 float(config.get("max_error_rate", .1)), int(config.get("min_samples", 20)),
                 config.get("status", "running"),
                 float(config.get("max_disagreement_rate", .2)),
                 bool(config.get("auto_promote", False)), utc_now()),
            )

    def get_deployment(self, tenant_id: str, skill_name: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM deployments WHERE tenant_id=%s AND skill_name=%s",
                (tenant_id, skill_name),
            ).fetchone()
        return dict(row) if row else None

    def record_deployment_result(
        self, tenant_id: str, skill_name: str, failed: bool,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE deployments SET samples=samples+1,errors=errors+%s,updated_at=%s "
                "WHERE tenant_id=%s AND skill_name=%s RETURNING *",
                (int(failed), utc_now(), tenant_id, skill_name),
            ).fetchone()
            if not row:
                return None
            value = dict(row)
            if (value["status"] == "running" and value["samples"] >= value["min_samples"]
                    and value["errors"] / value["samples"] > value["max_error_rate"]):
                conn.execute(
                    "UPDATE deployments SET status='rolled_back',canary_percent=0,shadow_percent=0,"
                    "updated_at=%s WHERE tenant_id=%s AND skill_name=%s",
                    (utc_now(), tenant_id, skill_name),
                )
                value["status"] = "rolled_back"
        return value

    def record_shadow_observation(
        self, tenant_id: str, skill_name: str, task_id: str, lane: str,
        primary: Dict[str, Any], candidate: Optional[Dict[str, Any]],
        disagreement: float, candidate_failed: bool = False,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO release_observations(tenant_id,skill_name,task_id,lane,"
                "primary_json,candidate_json,disagreement,candidate_failed,created_at) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s)",
                (
                    tenant_id, skill_name, task_id, lane,
                    json.dumps(primary, ensure_ascii=False),
                    json.dumps(candidate, ensure_ascii=False) if candidate is not None else None,
                    float(disagreement), bool(candidate_failed), utc_now(),
                ),
            )
            row = conn.execute(
                "UPDATE deployments SET shadow_samples=shadow_samples+1,"
                "disagreements=disagreements+%s,updated_at=%s "
                "WHERE tenant_id=%s AND skill_name=%s RETURNING *",
                (int(disagreement > 0), utc_now(), tenant_id, skill_name),
            ).fetchone()
            if not row:
                return None
            value = dict(row)
            disagreement_rate = (
                value["disagreements"] / value["shadow_samples"]
                if value["shadow_samples"] else 0.0
            )
            error_rate = value["errors"] / value["samples"] if value["samples"] else 0.0
            if (
                value["status"] == "running" and value["auto_promote"]
                and value["shadow_samples"] >= value["min_samples"]
                and disagreement_rate <= value["max_disagreement_rate"]
                and error_rate <= value["max_error_rate"]
                and not candidate_failed
            ):
                conn.execute(
                    "UPDATE deployments SET status='promoted',stable_version=candidate_version,"
                    "canary_percent=0,shadow_percent=0,updated_at=%s "
                    "WHERE tenant_id=%s AND skill_name=%s",
                    (utc_now(), tenant_id, skill_name),
                )
                value["status"] = "promoted"
        return value

    def list_release_observations(
        self, tenant_id: str, skill_name: str, limit: int = 100,
    ) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM release_observations WHERE tenant_id=%s AND skill_name=%s "
                "ORDER BY id DESC LIMIT %s",
                (tenant_id, skill_name, max(1, min(limit, 500))),
            ).fetchall()
        values = []
        for row in rows:
            item = dict(row)
            primary = item.pop("primary_json")
            candidate = item.pop("candidate_json")
            item["primary"] = json.loads(primary) if isinstance(primary, str) else primary
            item["candidate"] = (
                json.loads(candidate) if isinstance(candidate, str) else candidate
            )
            values.append(item)
        return values

    def create_alert(
        self, tenant_id: str, alert_key: str, severity: str, message: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO alerts(tenant_id,alert_key,severity,message,status,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,'open',%s,%s) ON CONFLICT(tenant_id,alert_key,status) DO NOTHING",
                (tenant_id, alert_key, severity, message[:1000], utc_now(), utc_now()),
            )

    def list_alerts(self, tenant_id: str, limit: int = 100) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE tenant_id=%s ORDER BY id DESC LIMIT %s",
                (tenant_id, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _annotation_case(row) -> Dict[str, Any]:
        value = dict(row)
        value["source"] = value.pop("source_json")
        for key in ("created_at", "updated_at", "exported_at"):
            if value.get(key) is not None:
                value[key] = value[key].isoformat()
        return value

    @staticmethod
    def _annotation_submission(row) -> Dict[str, Any]:
        value = dict(row)
        value["findings"] = value.pop("findings_json")
        value["evidence_urls"] = value.pop("evidence_urls_json")
        value["submitted_at"] = value["submitted_at"].isoformat()
        return value

    def create_annotation_case(self, case: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO annotation_cases(id,tenant_id,repository,pull_request,split,status,"
                "source_json,diff,diff_sha256,required_reviewers,created_by,created_at,updated_at,"
                "exported_at) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s)",
                (
                    case["id"], case["tenant_id"], case["repository"],
                    case["pull_request"], case["split"], case["status"],
                    json.dumps(case["source"], ensure_ascii=False), case["diff"],
                    case["diff_sha256"], case["required_reviewers"], case["created_by"],
                    case["created_at"], case["updated_at"], case.get("exported_at"),
                ),
            )
        return case

    def find_annotation_case(
        self, tenant_id: str, repository: str, pull_request: int,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM annotation_cases WHERE tenant_id=%s "
                "AND lower(repository)=lower(%s) AND pull_request=%s",
                (tenant_id, repository, pull_request),
            ).fetchone()
        return self._annotation_case(row) if row else None

    def get_annotation_case(
        self, case_id: str, tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM annotation_cases WHERE id=%s AND tenant_id=%s",
                (case_id, tenant_id),
            ).fetchone()
        return self._annotation_case(row) if row else None

    def list_annotation_cases(
        self, tenant_id: str, status: Optional[str] = None,
        split: Optional[str] = None, limit: int = 100,
    ) -> list:
        clauses = ["tenant_id=%s"]
        params: list = [tenant_id]
        if status:
            clauses.append("status=%s")
            params.append(status)
        if split:
            clauses.append("split=%s")
            params.append(split)
        params.append(max(1, min(limit, 5000)))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM annotation_cases WHERE " + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT %s", params,
            ).fetchall()
        return [self._annotation_case(row) for row in rows]

    def update_annotation_case_status(
        self, case_id: str, tenant_id: str, status: str, updated_at: str,
        exported_at: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            allowed = {
                "in_review": ("ready",),
                "needs_adjudication": ("ready", "in_review"),
                "approved": ("ready", "in_review", "needs_adjudication"),
                "exported": ("approved",),
            }.get(status)
            if not allowed:
                raise ValueError("invalid annotation status transition")
            cursor = conn.execute(
                "UPDATE annotation_cases SET status=%s,updated_at=%s,"
                "exported_at=COALESCE(%s,exported_at) WHERE id=%s AND tenant_id=%s "
                "AND status=ANY(%s)",
                (status, updated_at, exported_at, case_id, tenant_id, list(allowed)),
            )
            if cursor.rowcount == 1:
                return
            row = conn.execute(
                "SELECT status FROM annotation_cases WHERE id=%s AND tenant_id=%s",
                (case_id, tenant_id),
            ).fetchone()
            if not row:
                raise ValueError("annotation case not found")
            if row["status"] == status:
                return
            if status == "in_review" and row["status"] in {
                "needs_adjudication", "approved", "exported",
            }:
                return
            raise ValueError("annotation case status changed concurrently")

    def create_annotation_submission(self, submission: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as conn:
            case = conn.execute(
                "SELECT required_reviewers FROM annotation_cases WHERE id=%s AND tenant_id=%s "
                "FOR UPDATE", (submission["case_id"], submission["tenant_id"]),
            ).fetchone()
            if not case:
                raise ValueError("annotation case not found")
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM annotation_submissions WHERE case_id=%s AND tenant_id=%s",
                (submission["case_id"], submission["tenant_id"]),
            ).fetchone()["n"]
            if int(count) >= int(case["required_reviewers"]):
                raise ValueError("the required independent annotations are complete")
            try:
                conn.execute(
                    "INSERT INTO annotation_submissions(id,case_id,tenant_id,annotator_id,annotator,"
                    "verdict,findings_json,methodology,evidence_urls_json,revision,submitted_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s)",
                    (
                        submission["id"], submission["case_id"], submission["tenant_id"],
                        submission["annotator_id"], submission["annotator"],
                        submission["verdict"],
                        json.dumps(submission["findings"], ensure_ascii=False),
                        submission["methodology"],
                        json.dumps(submission["evidence_urls"], ensure_ascii=False),
                        submission["revision"], submission["submitted_at"],
                    ),
                )
            except Exception as exc:
                if getattr(exc, "sqlstate", "") == "23505":
                    raise ValueError(
                        "each user may submit only one independent annotation"
                    ) from exc
                raise
        return submission

    def list_annotation_submissions(self, case_id: str, tenant_id: str) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM annotation_submissions WHERE case_id=%s AND tenant_id=%s "
                "ORDER BY submitted_at,id", (case_id, tenant_id),
            ).fetchall()
        return [self._annotation_submission(row) for row in rows]

    def create_annotation_adjudication(self, value: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO annotation_adjudications(id,case_id,tenant_id,adjudicator_id,"
                    "adjudicator,verdict,findings_json,rationale,created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)",
                    (
                        value["id"], value["case_id"], value["tenant_id"],
                        value["adjudicator_id"], value["adjudicator"], value["verdict"],
                        json.dumps(value["findings"], ensure_ascii=False), value["rationale"],
                        value["created_at"],
                    ),
                )
            except Exception as exc:
                if getattr(exc, "sqlstate", "") == "23505":
                    raise ValueError("annotation case has already been adjudicated") from exc
                raise
        return value

    def get_annotation_adjudication(
        self, case_id: str, tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM annotation_adjudications WHERE case_id=%s AND tenant_id=%s",
                (case_id, tenant_id),
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["findings"] = value.pop("findings_json")
        value["created_at"] = value["created_at"].isoformat()
        return value

    def create_annotation_export(self, value: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO annotation_exports(id,tenant_id,name,version,manifest_json,"
                    "dataset_json,created_by,created_at) VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)",
                    (
                        value["id"], value["tenant_id"], value["name"], value["version"],
                        json.dumps(value["manifest"], ensure_ascii=False),
                        json.dumps(value["dataset"], ensure_ascii=False),
                        value["created_by"], value["created_at"],
                    ),
                )
            except Exception as exc:
                if getattr(exc, "sqlstate", "") == "23505":
                    raise ValueError("dataset name and version already exist") from exc
                raise
        return value

    def list_annotation_exports(self, tenant_id: str, limit: int = 100) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,tenant_id,name,version,manifest_json,created_by,created_at "
                "FROM annotation_exports WHERE tenant_id=%s ORDER BY created_at DESC LIMIT %s",
                (tenant_id, max(1, min(limit, 500))),
            ).fetchall()
        values = []
        for row in rows:
            item = dict(row)
            item["manifest"] = item.pop("manifest_json")
            item["created_at"] = item["created_at"].isoformat()
            values.append(item)
        return values

    def get_annotation_export(
        self, export_id: str, tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM annotation_exports WHERE id=%s AND tenant_id=%s",
                (export_id, tenant_id),
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["manifest"] = value.pop("manifest_json")
        value["dataset"] = value.pop("dataset_json")
        value["created_at"] = value["created_at"].isoformat()
        return value

    def save_installation(
        self, installation_id: int, account_login: str, tenant_id: str = "default"
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO installations(installation_id,account_login,created_at,tenant_id) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT(installation_id) DO UPDATE "
                "SET account_login=EXCLUDED.account_login,created_at=EXCLUDED.created_at,"
                "tenant_id=EXCLUDED.tenant_id",
                (installation_id, account_login, utc_now(), tenant_id),
            )

    def installation_tenant(self, installation_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT tenant_id FROM installations WHERE installation_id=%s",
                (installation_id,),
            ).fetchone()
        return row["tenant_id"] if row else None

    def dashboard_stats(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        with self._connect() as conn:
            where = " WHERE tenant_id=%s" if tenant_id is not None else ""
            params = (tenant_id,) if tenant_id is not None else ()
            row = conn.execute(
                "SELECT COUNT(*) AS total,COUNT(*) FILTER(WHERE state='SUCCESS') AS success,"
                "COUNT(*) FILTER(WHERE state='FAILED') AS failed FROM tasks" + where,
                params,
            ).fetchone()
            if tenant_id is None:
                failures = conn.execute(
                    "SELECT COUNT(*) AS n FROM failure_cases WHERE resolved=FALSE"
                ).fetchone()["n"]
            else:
                failures = conn.execute(
                    "SELECT COUNT(*) AS n FROM failure_cases f JOIN tasks t ON t.id=f.task_id "
                    "WHERE f.resolved=FALSE AND t.tenant_id=%s", (tenant_id,)
                ).fetchone()["n"]
            skills = conn.execute(
                "SELECT COUNT(*) AS n FROM skill_versions WHERE active=TRUE"
            ).fetchone()["n"]
            if tenant_id is None:
                skills += conn.execute(
                    "SELECT COUNT(*) AS n FROM skill_artifact_versions WHERE active=TRUE"
                ).fetchone()["n"]
            else:
                skills += conn.execute(
                    "SELECT COUNT(*) AS n FROM skill_artifact_versions "
                    "WHERE tenant_id=%s AND active=TRUE", (tenant_id,)
                ).fetchone()["n"]
        return {"tasks_total": row["total"], "tasks_success": row["success"], "tasks_failed": row["failed"],
                "success_rate": round(row["success"] / row["total"], 4) if row["total"] else 0.0,
                "unresolved_failure_cases": failures, "active_skill_versions": skills}


def create_store(database_url: str, sqlite_path: str, auto_migrate: bool = True):
    """Backward-compatible factory; new code should import create_repository."""
    if database_url.startswith(
        ("postgres://", "postgresql://", "postgresql+psycopg://")
    ):
        return PostgresTaskStore(database_url, auto_migrate=auto_migrate)
    if database_url:
        raise ValueError("unsupported CODEEVO_DATABASE_URL")
    from .store import TaskStore
    return TaskStore(sqlite_path)
