"""Extraction runs (schema.md 3.4). The provider is behind an interface; B1 uses a fake only."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Integer, LargeBinary, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy import UUIDT, Base, TenantMixin, enum_check, tenant_args, tfk


class ExtractionRunRow(TenantMixin, Base):
    __tablename__ = "extraction_runs"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "document_id", "input_sha256", "provider", "model", "prompt_version"),
        tfk("document_id", "documents"),
        CheckConstraint(enum_check("status", ("succeeded", "failed")), name="status"),
        Index(
            "uq_extraction_runs_in_use", "tenant_id", "document_id", unique=True, postgresql_where="in_use"
        ),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    input_sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[dict | None] = mapped_column(JSONB)
    verification: Mapped[dict] = mapped_column(JSONB, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    in_use: Mapped[bool] = mapped_column(nullable=False, server_default="false")
