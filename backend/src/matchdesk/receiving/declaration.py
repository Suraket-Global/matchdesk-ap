"""The "We have no warehouse receiving records" declaration (S-03; TRD 12
``POST /onboarding/no-receiving-declaration``; B9).

A recorded fact, never a rule change: every invoiced line still carries a ``receipt_absent``
exception (MH-07, CLAUDE.md false pass 2); price, ordered-quantity and duplicate checks still run;
coverage reads 0 % and the report is two-way only. Declaring and withdrawing are audited; the
declaration is withdrawn automatically when a receiving import is committed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ConflictError
from matchdesk.receiving.models import NoReceivingDeclaration, ReceivingImportRow

STATEMENT = (
    "We have no warehouse receiving records for the purchase orders in this back-test. Every invoiced "
    "line will carry a receipt-absent exception; price, ordered-quantity and duplicate checks still run; "
    "the report is a two-way match only."
)


def current_declaration(s: Session) -> NoReceivingDeclaration | None:
    return s.scalar(select(NoReceivingDeclaration).where(NoReceivingDeclaration.withdrawn_at.is_(None)))


def declare_no_receiving(s: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> NoReceivingDeclaration:
    """Record the declaration (controller). Refused while a receiving import counts."""
    found = current_declaration(s)
    if found is not None:
        return found
    committed = s.scalar(
        select(func.count()).select_from(ReceivingImportRow).where(ReceivingImportRow.state == "succeeded")
    )
    if committed:
        raise ConflictError(
            "receiving records are imported for this account; void those imports before declaring that none exist"
        )
    row = NoReceivingDeclaration(tenant_id=tenant_id, statement=STATEMENT, declared_by=user_id)
    s.add(row)
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="receiving.no_records_declared",
        entity_type="no_receiving_declaration",
        entity_id=row.id,
        after={"statement": STATEMENT},
    )
    return row


def withdraw_declaration(
    s: Session, row: NoReceivingDeclaration, user_id: uuid.UUID, reason: str, actor_type: str = "user"
) -> NoReceivingDeclaration:
    if row.withdrawn_at is not None:
        return row
    row.withdrawn_at, row.withdrawn_by = datetime.now(UTC), user_id
    row.withdraw_reason = reason.strip() or None
    s.flush()
    write_audit(
        s,
        row.tenant_id,
        actor_type=actor_type,
        actor_user_id=user_id,
        action="receiving.no_records_withdrawn",
        entity_type="no_receiving_declaration",
        entity_id=row.id,
        after={"reason": row.withdraw_reason},
    )
    return row


def describe_declaration(
    row: NoReceivingDeclaration | None, names: dict[uuid.UUID, str]
) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "statement": row.statement,
        "declared_by": str(row.declared_by),
        "declared_by_name": names.get(row.declared_by),
        "declared_at": row.created_at.isoformat(),
    }
