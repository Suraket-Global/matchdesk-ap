"""Structured JSON logging with correlation IDs and a scrubber (TRD section 8.6, R-12).

Never logged: document text, extracted line content, prices, tokens, cookies,
email bodies, user-supplied file names. Log calls pass only identifiers and
event names; the scrubber drops any extra field outside an allow-list, so a
careless ``extra={"unit_price": ...}`` never reaches the output.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import uuid
from datetime import UTC, datetime

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
_tenant_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)

ALLOWED_FIELDS = frozenset(
    {
        "event",
        "tenant_id",
        "user_id",
        "job_id",
        "match_run_id",
        "entity_id",
        "entity_type",
        "state",
        "from_state",
        "to_state",
        "count",
        "status_code",
        "path",
        "method",
        "duration_ms",
        "settings_hash",
        "service",
        "reason",
        "task",
    }
)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def set_correlation_id(value: str | None) -> contextvars.Token[str | None]:
    return _correlation_id.set(value)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_log_tenant(value: str | None) -> contextvars.Token[str | None]:
    return _tenant_id.set(value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "correlation_id": _correlation_id.get(),
        }
        tenant = _tenant_id.get()
        if tenant:
            payload["tenant_id"] = tenant
        for key, value in record.__dict__.items():
            if key in ALLOWED_FIELDS and key != "event":
                payload[key] = value if isinstance(value, (int, bool)) else str(value)
        return json.dumps(payload, sort_keys=True)


def configure_logging(level: str = "INFO", stream: object | None = None) -> None:
    handler = logging.StreamHandler(stream or sys.stdout)  # type: ignore[arg-type]
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
