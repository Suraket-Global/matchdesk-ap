"""Intake tables (schema.md 3.4): batches, documents, invoices and their lines."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy import MONEY, PRICE, QTY, UUIDT, Base, TenantMixin, enum_check, tenant_args, tfk

DOCUMENT_STATES = ("queued", "running", "succeeded", "needs_review", "retry_wait", "failed", "duplicate_file")


class UploadBatch(TenantMixin, Base):
    __tablename__ = "upload_batches"
    __table_args__ = tenant_args(CheckConstraint(enum_check("source", ("upload", "email")), name="source"))
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="upload")
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentRow(TenantMixin, Base):
    __tablename__ = "documents"
    __table_args__ = tenant_args(
        tfk("batch_id", "upload_batches"),
        CheckConstraint(
            enum_check("purpose", ("invoice", "receiving", "export", "inbound_raw")), name="purpose"
        ),
        CheckConstraint(enum_check("source", ("upload", "email", "system")), name="source"),
        CheckConstraint(enum_check("state", DOCUMENT_STATES), name="state"),
        CheckConstraint("blob_key like 't/' || tenant_id::text || '/%'", name="blob_key_tenant"),
        Index(
            "uq_documents_tenant_invoice_sha",
            "tenant_id",
            "sha256",
            unique=True,
            postgresql_where="purpose = 'invoice' and state <> 'duplicate_file' and deleted_at is null",
        ),
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    blob_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(Text)
    duplicate_of_document_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceRow(TenantMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "document_id", "page_from"),
        tfk("document_id", "documents"),
        tfk("vendor_id", "vendors"),
        tfk("purchase_order_id", "purchase_orders"),
        CheckConstraint(enum_check("doc_type", ("invoice", "credit_note")), name="doc_type"),
        CheckConstraint(
            enum_check(
                "verification_status", ("passed", "failed", "human_confirmed", "human_confirmed_inconsistent")
            ),
            name="verification_status",
        ),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    page_from: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    page_to: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    file_order_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    doc_number: Mapped[str | None] = mapped_column(Text)
    doc_number_norm: Mapped[str | None] = mapped_column(Text)
    doc_date: Mapped[date | None] = mapped_column(Date)
    po_number_read: Mapped[str | None] = mapped_column(Text)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    references_invoice_number: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str | None] = mapped_column(String(3))
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class InvoiceLineRow(TenantMixin, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "invoice_id", "line_no"),
        tfk("invoice_id", "invoices"),
        CheckConstraint(enum_check("line_kind", ("item", "freight", "fee", "discount")), name="line_kind"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    supplier_item_code: Mapped[str | None] = mapped_column(Text)
    qty: Mapped[Decimal | None] = mapped_column(QTY)
    uom: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal | None] = mapped_column(PRICE)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    line_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="item")
    field_sources: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
