"""Structured application logging without request-body or credential fields."""
import json
import logging
import sys
from datetime import datetime, timezone

from .observability import trace_id_var


SAFE_EXTRA_FIELDS = (
    "event",
    "request_id",
    "method",
    "path",
    "status",
    "duration_ms",
    "client_ip",
    "tenant_id",
    "task_id",
    "host",
    "port",
    "persistence",
    "queue",
    "orchestrator",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = trace_id_var.get()
        if trace_id:
            payload["trace_id"] = trace_id
        for name in SAFE_EXTRA_FIELDS:
            value = getattr(record, name, None)
            if value not in (None, ""):
                payload[name] = value
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO", log_format: str = "json") -> None:
    normalized_level = level.upper()
    if normalized_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("CODEEVO_LOG_LEVEL is invalid")
    if log_format not in {"json", "text"}:
        raise ValueError("CODEEVO_LOG_FORMAT must be json or text")

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(normalized_level)
