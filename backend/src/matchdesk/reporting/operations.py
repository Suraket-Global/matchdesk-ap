"""The worker's scheduled operations and their record (B10, outside QA item 8).

Every operation runs on its own: one failing (a weekly email that cannot be sent, say) no longer
stops raw-email cleanup, receiving-draft cleanup, archive expiry or due deletions in the same cycle.
Each run writes ``scheduled_operations`` (global, no tenant data): last start, last success, last
failure with the error class, and consecutive failures. The operator console S-18 lists an operation
as failing when its last run failed, and as late when it has not succeeded for ``LATE_AFTER``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from matchdesk.core import get_logger
from matchdesk.reporting.models import ScheduledOperation
from matchdesk.tenancy import global_session

log = get_logger("matchdesk.reporting.operations")

# The worker runs every operation each minute; ten missed minutes is late [assumption].
LATE_AFTER = timedelta(minutes=10)
OPERATION_WORDS = {
    "weekly_summary": "Weekly summary email",
    "raw_email_cleanup": "Raw inbound email removal (7 days)",
    "receiving_draft_cleanup": "Receiving draft removal (7 days)",
    "archive_expiry": "Archive expiry (24 hours)",
    "due_deletions": "Account deletions that are due",
}


def run_operations(
    engine: Engine, operations: list[tuple[str, Callable[[], int]]], now: datetime | None = None
) -> dict[str, int | None]:
    """Run each operation with its own error handling and record the outcome. Returns the count each
    one reported, or None for one that failed."""
    out: dict[str, int | None] = {}
    for name, fn in operations:
        started = now or datetime.now(UTC)
        _record(engine, name, started=started)
        try:
            result = int(fn() or 0)
        except Exception as exc:  # recorded; the next operation still runs
            log.error("scheduled_operation_failed", extra={"operation": name, "reason": type(exc).__name__})
            _record(engine, name, failed=datetime.now(UTC), error=type(exc).__name__)
            out[name] = None
            continue
        _record(engine, name, succeeded=datetime.now(UTC), result=result)
        out[name] = result
    return out


def _record(
    engine: Engine,
    name: str,
    started: datetime | None = None,
    succeeded: datetime | None = None,
    failed: datetime | None = None,
    error: str | None = None,
    result: int | None = None,
) -> None:
    values: dict[str, Any] = {"name": name}
    update: dict[str, Any] = {}
    if started is not None:
        values["last_started_at"] = update["last_started_at"] = started
    if succeeded is not None:
        values["last_success_at"] = update["last_success_at"] = succeeded
        values["consecutive_failures"] = update["consecutive_failures"] = 0
        values["last_result"] = update["last_result"] = result
    if failed is not None:
        values["last_failure_at"] = update["last_failure_at"] = failed
        values["last_error"] = update["last_error"] = error
        values["consecutive_failures"] = 1
        update["consecutive_failures"] = ScheduledOperation.consecutive_failures + 1
    with global_session(engine) as g:
        g.execute(
            pg_insert(ScheduledOperation)
            .values(**values)
            .on_conflict_do_update(index_elements=["name"], set_=update)
        )


def describe_operations(engine: Engine, now: datetime | None = None) -> list[dict[str, Any]]:
    """S-18 "Operations": failing first, then late, then the rest; each with its last success."""
    at = now or datetime.now(UTC)
    with global_session(engine) as g:
        rows = {r.name: r for r in g.scalars(select(ScheduledOperation)).all()}
    items: list[dict[str, Any]] = []
    for name, words in OPERATION_WORDS.items():
        r = rows.get(name)
        failing = bool(r and r.consecutive_failures > 0)
        late = r is None or r.last_success_at is None or at - r.last_success_at > LATE_AFTER
        items.append(
            {
                "name": name,
                "label": words,
                "state": "failing" if failing else "late" if late else "ok",
                "last_success_at": r.last_success_at.isoformat() if r and r.last_success_at else None,
                "last_failure_at": r.last_failure_at.isoformat() if r and r.last_failure_at else None,
                "last_error": r.last_error if failing and r else None,
                "consecutive_failures": r.consecutive_failures if r else 0,
            }
        )
    order = {"failing": 0, "late": 1, "ok": 2}
    return sorted(items, key=lambda i: order[i["state"]])
