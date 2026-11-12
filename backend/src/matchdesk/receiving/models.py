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
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy import QTY, UUIDT, Base, TenantMixin, enum_check, tenant_args, tfk

IMPORT_STATES = ("draft", "queued", "running", "succeeded", "failed", "voided")
# qbo_item_receipt_export: a QuickBooks Online item-receipt report or CSV export (no API entity
# exists); always class A, each row tested by receiving.item_receipt_rejection (C1, migration 0008).
SOURCE_TYPES = ("spreadsheet", "delivery_document", "qbo_item_receipt_export")


class ReceivingMapping(TenantMixin, Base):
    """A saved column mapping: target field -> source column header (schema.md 3.3)."""

    __tablename__ = "receiving_mappings"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "name"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    columns: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))


class ReceivingAttestation(TenantMixin, Base):
    """The controller's attestation of the account's receiving evidence and, for QuickBooks item
    receipts, the accounts-payable users whose receipts are not independent (C1; T-3.2.1). The
    latest row is in force; rows are never updated."""

    __tablename__ = "receiving_attestations"
    __table_args__ = tenant_args(
        CheckConstraint(enum_check("evidence_class", ("A", "B", "C")), name="evidence_class")
    )
    evidence_class: Mapped[str] = mapped_column(Text, nullable=False)
    source_description: Mapped[str] = mapped_column(Text, nullable=False)
    ap_staff: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    attested_by: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)


class ReceivingImportRow(TenantMixin, Base):
    __tablename__ = "receiving_imports"
    __table_args__ = tenant_args(
        tfk("document_id", "documents"),
        tfk("mapping_id", "receiving_mappings"),
        CheckConstraint(enum_check("evidence_class", ("A", "B", "C")), name="evidence_class"),
        CheckConstraint(enum_check("source_type", SOURCE_TYPES), name="source_type"),
        CheckConstraint(
            "source_type <> 'qbo_item_receipt_export' or evidence_class = 'A'",
            name="qbo_item_receipt_class_a",
        ),
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
    kept_by_name: Mapped[str | None] = mapped_column(Text)
    mapping_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    column_map: Mapped[dict | None] = mapped_column(JSONB)
    rows_total: Mapped[int | None] = mapped_column(Integer)
    rows_valid: Mapped[int | None] = mapped_column(Integer)
    rows_rejected: Mapped[int | None] = mapped_column(Integer)
    # Row number and reason, plus only the offending value (schema.md 3.3).
    rejected_rows: Mapped[list | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    committed_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    receiver_ref: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[int | None] = mapped_column(Integer)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class NoReceivingDeclaration(TenantMixin, Base):
    """The controller's statement that the account keeps no warehouse receiving records (S-03; B9).

    It records a fact and changes no rule: every invoiced line stays a ``receipt_absent`` exception
    (MH-07; CLAUDE.md false pass 2), the price, ordered-quantity and duplicate checks still run, and
    the report is two-way only. At most one declaration is in force; withdrawing it keeps the row."""

    __tablename__ = "no_receiving_declarations"
    __table_args__ = tenant_args(
        Index(
            "uq_no_receiving_declarations_in_force",
            "tenant_id",
            unique=True,
            postgresql_where="withdrawn_at is null",
        ),
        CheckConstraint("(withdrawn_at is null) = (withdrawn_by is null)", name="withdrawn_pair"),
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    declared_by: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    withdrawn_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdraw_reason: Mapped[str | None] = mapped_column(Text)
