"""Append-only audit events written inside the business transaction (TRD 8.6, MH-13)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from matchdesk.audit.models import AuditEvent
from matchdesk.core import get_correlation_id


def write_audit(
    s: Session,
    tenant_id: uuid.UUID,
    *,
    actor_type: str,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    corr = get_correlation_id()
    s.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            correlation_id=uuid.UUID(corr) if corr else None,
        )
    )


__all__ = ["AuditEvent", "write_audit"]
