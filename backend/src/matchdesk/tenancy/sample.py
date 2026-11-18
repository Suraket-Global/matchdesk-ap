"""The 7-day free trial, called "sample" in code (owner, 2026-11-18): before any fee, a new account checks a sample of one
month. Up to ``SAMPLE_INVOICE_LIMIT`` invoice files, for ``SAMPLE_DAYS`` days from the account's
creation; the approved report and its exports belong to the paid pilot. The operator starts the
pilot (``tenants.status`` 'sample' -> 'pilot'), which lifts every limit here.

Read with raw SQL so every module can call it without importing another module's models.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from matchdesk.core import ConflictError

SAMPLE_DAYS = 7
SAMPLE_INVOICE_LIMIT = 100


def sample_ends(created: datetime) -> datetime:
    return created + timedelta(days=SAMPLE_DAYS)


_PROGRESS_SQL = text(
    """
    select
      exists (select 1 from qbo_connections where tenant_id = cast(:t as uuid) and status = 'connected')
        as qbo_connected,
      exists (select 1 from receiving_imports where tenant_id = cast(:t as uuid) and state = 'succeeded')
        or exists (select 1 from no_receiving_declarations
                   where tenant_id = cast(:t as uuid) and withdrawn_at is null) as receiving_loaded,
      (select count(*) from documents where tenant_id = cast(:t as uuid) and purpose = 'invoice'
         and state <> 'duplicate_file' and deleted_at is null and removed_at is null) as invoices,
      (select count(*) from documents where tenant_id = cast(:t as uuid) and purpose = 'invoice'
         and state = 'needs_review' and deleted_at is null and removed_at is null) as to_review,
      (select count(*) from exceptions where tenant_id = cast(:t as uuid)
         and status in ('open', 'pending_approval') and value_class = 'finding_candidate') as findings,
      (select coalesce(sum(reported_amount), 0) from exceptions where tenant_id = cast(:t as uuid)
         and status in ('open', 'pending_approval') and value_class = 'finding_candidate') as findings_amount
    """
)

# The trial's steps in order (the onboarding checklist, S-03); the first not done is the next one.
NEXT_STEPS = ("connect_qbo", "load_receiving", "upload_invoices", "review_documents", "read_findings")


def trial_progress(s: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    """What the account has done so far, as facts and counts only (no document content): for the
    trial banner, the reminder emails and the operator's list of trials."""
    row = s.execute(_PROGRESS_SQL, {"t": str(tenant_id)}).one()
    invoices, to_review = int(row.invoices), int(row.to_review)
    progress: dict[str, Any] = {
        "qbo_connected": bool(row.qbo_connected),
        "receiving_loaded": bool(row.receiving_loaded),
        "invoices": invoices,
        "to_review": to_review,
        "findings": int(row.findings),
        "findings_amount": str(row.findings_amount),
    }
    done = {
        "connect_qbo": bool(row.qbo_connected),
        "load_receiving": bool(row.receiving_loaded),
        "upload_invoices": invoices > 0,
        "review_documents": invoices > 0 and to_review == 0,
        "read_findings": False,
    }
    progress["next_step"] = next(k for k in NEXT_STEPS if not done[k])
    progress["steps_done"] = sum(1 for k in NEXT_STEPS[:4] if done[k])
    return progress


def sample_state(s: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> dict[str, Any] | None:
    """None for an account that is not on the free sample check; else its limits and use."""
    row = s.execute(
        text("select status, sample_ends_at from tenants where id = cast(:t as uuid)"), {"t": str(tenant_id)}
    ).first()
    if row is None or row[0] != "sample":
        return None
    at = now or datetime.now(UTC)
    ends: datetime | None = row[1]
    used = int(
        s.scalar(
            text(
                "select count(*) from documents where tenant_id = cast(:t as uuid) and purpose = 'invoice' "
                "and state <> 'duplicate_file' and deleted_at is null and removed_at is null"
            ),
            {"t": str(tenant_id)},
        )
        or 0
    )
    started = ends - timedelta(days=SAMPLE_DAYS) if ends else None
    day = min(SAMPLE_DAYS, max(1, (at - started).days + 1)) if started else None
    return {
        "ends_at": ends.isoformat() if ends else None,
        "ended": ends is not None and at >= ends,
        "day": day,
        "days": SAMPLE_DAYS,
        "invoices_used": used,
        "invoice_limit": SAMPLE_INVOICE_LIMIT,
        "progress": trial_progress(s, tenant_id),
    }


def assert_upload_allowed(s: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> None:
    """Refuse a new invoice file once the sample has ended or its invoice limit is reached."""
    st = sample_state(s, tenant_id, now)
    if st is None:
        return
    if st["ended"]:
        raise ConflictError(
            "The 7-day free trial has ended, so no more files can be added. "
            "Ask MatchDesk to start the pilot to check the whole month."
        )
    if st["invoices_used"] >= SAMPLE_INVOICE_LIMIT:
        raise ConflictError(
            f"The free trial covers up to {SAMPLE_INVOICE_LIMIT} invoices, and they are all used. "
            "Ask MatchDesk to start the pilot to check the whole month."
        )


def assert_pilot_feature(s: Session, tenant_id: uuid.UUID, what: str) -> None:
    """Refuse what belongs to the paid pilot (an approved report, an export) during the sample."""
    if sample_state(s, tenant_id) is not None:
        raise ConflictError(
            f"{what} comes with the paid pilot. During the free trial the findings are shown on "
            "screen; ask MatchDesk to start the pilot."
        )
