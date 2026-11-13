"""PostgreSQL-backed job queue and the job wrapper (T-2.2.1 (d); TRD 6.3, 8.2).

Jobs are enqueued in the same transaction as the business change. The wrapper
refuses a payload without ``tenant_id`` and sets the tenant context before the
handler runs, so a handler can only see its own tenant's rows (IT-02).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from matchdesk.core import get_logger, new_correlation_id, set_correlation_id, set_log_tenant
from matchdesk.tenancy.db import get_engine, global_session, session

log = get_logger("matchdesk.jobs")
RETRY_DELAYS = (timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=10))

Handler = Callable[[Session, dict[str, Any]], None]


@dataclass(frozen=True)
class ClaimedJob:
    """A claimed job. ``attempts`` is the claim's number: every claim increments it, and the final
    update requires the same number and state ``running``, so the late result of a claim whose lease
    expired and was taken by another worker changes nothing (B10, outside QA item 7; R-01)."""

    id: uuid.UUID
    task: str
    payload: dict[str, Any]
    attempts: int


class PermanentJobError(Exception):
    """Do not retry (for example an unreadable file)."""


def enqueue(
    s: Session,
    task: str,
    tenant_id: uuid.UUID | str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
) -> uuid.UUID:
    body = {**payload, "tenant_id": str(tenant_id), "correlation_id": correlation_id or new_correlation_id()}
    row = s.execute(
        text(
            "insert into job_queue (task, payload, run_after) values (:t, cast(:p as jsonb), now()) "
            "returning id"
        ),
        {"t": task, "p": _json(body)},
    ).one()
    return uuid.UUID(str(row[0]))


def enqueue_raw(s: Session, task: str, payload: dict[str, Any]) -> uuid.UUID:
    """Enqueue without adding a tenant (used only by tests that prove the wrapper rejects it)."""
    row = s.execute(
        text(
            "insert into job_queue (task, payload, run_after) values (:t, cast(:p as jsonb), now()) "
            "returning id"
        ),
        {"t": task, "p": _json(payload)},
    ).one()
    return uuid.UUID(str(row[0]))


def claim(lease_seconds: int = 300, engine: Engine | None = None) -> ClaimedJob | None:
    """Take one ready job, or one whose lease expired, with a new lease."""
    with global_session(engine) as s:
        row = s.execute(
            text(
                """
                update job_queue set state = 'running', attempts = attempts + 1,
                       lease_expires_at = now() + make_interval(secs => :lease)
                 where id = (
                   select id from job_queue
                    where (state = 'queued' and run_after <= now())
                       or (state = 'running' and lease_expires_at < now())
                    order by run_after, id
                    for update skip locked limit 1)
                returning id, task, payload, attempts
                """
            ),
            {"lease": lease_seconds},
        ).first()
    if row is None:
        return None
    return ClaimedJob(id=row[0], task=row[1], payload=dict(row[2]), attempts=row[3])


def run_claimed(job: ClaimedJob, handlers: dict[str, Handler], engine: Engine | None = None) -> str:
    """Run one claimed job through the wrapper. Returns the job's final state."""
    eng = engine or get_engine()
    tenant_id = job.payload.get("tenant_id")
    set_correlation_id(str(job.payload.get("correlation_id") or new_correlation_id()))
    if not tenant_id:
        log.warning("job_rejected_no_tenant", extra={"job_id": str(job.id), "task": job.task})
        return _finish(eng, job, "failed", "missing tenant_id")
    handler = handlers.get(job.task)
    if handler is None:
        return _finish(eng, job, "failed", "unknown task")
    set_log_tenant(str(tenant_id))
    try:
        with session(tenant_id, eng) as s:
            handler(s, job.payload)
    except PermanentJobError as exc:
        return _finish(eng, job, "failed", type(exc).__name__)
    except Exception as exc:  # transient: retry with backoff, then fail
        log.exception("job_error", extra={"job_id": str(job.id), "task": job.task})
        if job.attempts > len(RETRY_DELAYS):
            return _finish(eng, job, "failed", type(exc).__name__)
        delay = RETRY_DELAYS[job.attempts - 1]
        with global_session(eng) as s:
            moved = s.execute(
                text(
                    "update job_queue set state = 'queued', run_after = :at, lease_expires_at = null, "
                    "last_error = :e where id = :id and attempts = :n and state = 'running' returning id"
                ),
                {
                    "at": datetime.now(UTC) + delay,
                    "e": type(exc).__name__,
                    "id": str(job.id),
                    "n": job.attempts,
                },
            ).first()
        if moved is None:
            log.warning("job_claim_superseded", extra={"job_id": str(job.id), "attempt": job.attempts})
            return "superseded"
        return "queued"
    finally:
        set_log_tenant(None)
    return _finish(eng, job, "succeeded", None)


def _finish(engine: Engine, job: ClaimedJob, state: str, error: str | None) -> str:
    """Write the result only for the claim that is still current (same attempt, still running).
    Returns the state written, or ``superseded`` when a newer claim owns the job."""
    with global_session(engine) as s:
        written = s.execute(
            text(
                "update job_queue set state = :s, last_error = :e, lease_expires_at = null "
                "where id = :id and attempts = :n and state = 'running' returning id"
            ),
            {"s": state, "e": error, "id": str(job.id), "n": job.attempts},
        ).first()
    if written is None:
        log.warning("job_claim_superseded", extra={"job_id": str(job.id), "attempt": job.attempts})
        return "superseded"
    log.info("job_finished", extra={"job_id": str(job.id), "state": state})
    return state


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, default=str)
