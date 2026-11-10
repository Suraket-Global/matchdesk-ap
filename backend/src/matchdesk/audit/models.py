"""Append-only audit log (schema.md 3.6). The application role has INSERT and SELECT only (IT-24)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy.db import Base, TenantMixin, tenant_args
from matchdesk.tenancy.types import UUIDT, enum_check


class AuditEvent(TenantMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = tenant_args(
        CheckConstraint(enum_check("actor_type", ("user", "operator", "job", "system")), name="actor_type")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
