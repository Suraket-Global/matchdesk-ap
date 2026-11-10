"""Receiving evidence (schema.md 3.3). Class C never counts; QuickBooks quantities are not here."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy.db import Base, TenantMixin, tenant_args, tfk
from matchdesk.tenancy.types import QTY, UUIDT, enum_check

IMPORT_STATES = ("draft", "queued", "running", "succeeded", "failed", "voided")


class ReceivingImportRow(TenantMixin, Base):
    __tablename__ = "receiving_imports"
    __table_args__ = tenant_args(
        tfk("document_id", "documents"),
        CheckConstraint(enum_check("evidence_class", ("A", "B", "C")), name="evidence_class"),
        CheckConstraint(enum_check("source_type", ("spreadsheet", "delivery_document")), name="source_type"),
        CheckConstraint(enum_check("state", IMPORT_STATES), name="state"),
        CheckConstraint(
            "not declared_complete or (coverage_start is not null and coverage_end is not null)",
            name="coverage_declared",
        ),
        Index(
            "uq_receiving_imports_tenant_file",
            "tenant_id",
            "file_sha256",
            unique=True,
            postgresql_where="state not in ('voided', 'draft', 'failed')",
        ),
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_class: Mapped[str] = mapped_column(Text, nullable=False)
    declared_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    coverage_start: Mapped[date | None] = mapped_column(Date)
    coverage_end: Mapped[date | None] = mapped_column(Date)
    document_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    file_sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReceiptRow(TenantMixin, Base):
    __tablename__ = "receipts"
    __table_args__ = tenant_args(
        tfk("receiving_import_id", "receiving_imports"), tfk("purchase_order_id", "purchase_orders")
    )
    receiving_import_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    receiver_marks_present: Mapped[bool | None] = mapped_column(Boolean)
    receiver_name: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ReceiptLineRow(TenantMixin, Base):
    __tablename__ = "receipt_lines"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "receiving_import_id", "source_row"),
        tfk("receipt_id", "receipts"),
        tfk("receiving_import_id", "receiving_imports"),
        tfk("po_line_id", "po_lines"),
        CheckConstraint("qty_received <> 0", name="qty_nonzero"),
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    receiving_import_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    qty_received: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    uom: Mapped[str | None] = mapped_column(Text)
    qty_in_po_uom: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    added_after_exception: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    late_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
