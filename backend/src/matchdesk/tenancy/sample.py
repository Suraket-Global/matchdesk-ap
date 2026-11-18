"""The free sample check (owner, 2026-11-18): before any fee, a new account checks a sample of one
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
    return {
        "ends_at": ends.isoformat() if ends else None,
        "ended": ends is not None and at >= ends,
        "invoices_used": used,
        "invoice_limit": SAMPLE_INVOICE_LIMIT,
    }


def assert_upload_allowed(s: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> None:
    """Refuse a new invoice file once the sample has ended or its invoice limit is reached."""
    st = sample_state(s, tenant_id, now)
    if st is None:
        return
    if st["ended"]:
        raise ConflictError(
            "The free sample check has ended, so no more files can be added. "
            "Ask MatchDesk to start the pilot to check the whole month."
        )
    if st["invoices_used"] >= SAMPLE_INVOICE_LIMIT:
        raise ConflictError(
            f"The free sample check covers up to {SAMPLE_INVOICE_LIMIT} invoices, and they are all used. "
            "Ask MatchDesk to start the pilot to check the whole month."
        )


def assert_pilot_feature(s: Session, tenant_id: uuid.UUID, what: str) -> None:
    """Refuse what belongs to the paid pilot (an approved report, an export) during the sample."""
    if sample_state(s, tenant_id) is not None:
        raise ConflictError(
            f"{what} comes with the paid pilot. During the free sample check the findings are shown on "
            "screen; ask MatchDesk to start the pilot."
        )
