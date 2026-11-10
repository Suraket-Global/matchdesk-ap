"""Kernel tables: idempotency keys (tenant) and the job queue (global, identifiers only)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy.db import Base, GlobalMixin, TenantMixin, tenant_args
from matchdesk.tenancy.types import UUIDT, enum_check


class IdempotencyKey(TenantMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "user_id", "key"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    result_entity_type: Mapped[str | None] = mapped_column(Text)
    result_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Job(GlobalMixin, Base):
    """PostgreSQL-backed job queue (B1 stand-in for Procrastinate; TRD section 4).

    Payloads hold identifiers, ``tenant_id`` and ``correlation_id`` only, never document content.
    """

    __tablename__ = "job_queue"
    __table_args__ = (
        CheckConstraint(enum_check("state", ("queued", "running", "succeeded", "failed")), name="state"),
        Index("ix_job_queue_ready", "state", "run_after"),
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
