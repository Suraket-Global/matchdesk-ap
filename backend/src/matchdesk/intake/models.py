"""Intake tables (schema.md 3.4): batches, documents, invoices and their lines."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement

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
        CheckConstraint("(removed_at is null) = (removed_by is null)", name="removed_pair"),
        Index(
            "uq_documents_tenant_invoice_sha",
            "tenant_id",
            "sha256",
            unique=True,
            postgresql_where=(
                "purpose = 'invoice' and state <> 'duplicate_file' and deleted_at is null and removed_at is null"
            ),
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
    original_name: Mapped[str | None] = mapped_column(Text)  # S2; never used in paths or logs
    page_count: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # B12: deleted by a person (soft). The row and file stay until retention removes them; nothing
    # reads a removed document as a live input. ``deleted_at`` means the file itself is gone.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    removed_reason: Mapped[str | None] = mapped_column(Text)


def live_invoice() -> ColumnElement[bool]:
    """True for an invoice whose document was not deleted by a person (B12). Every read of invoices
    as inputs, history, lists or reports filters with this."""
    removed = select(DocumentRow.id).where(DocumentRow.removed_at.is_not(None))
    return InvoiceRow.document_id.not_in(removed)


class InvoiceRow(TenantMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "document_id", "page_from"),
        tfk("document_id", "documents"),
        tfk("vendor_id", "vendors"),
        tfk("purchase_order_id", "purchase_orders"),
        tfk("extraction_run_id", "extraction_runs"),
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
    vendor_name_read: Mapped[str | None] = mapped_column(Text)
    subtotal: Mapped[Decimal | None] = mapped_column(MONEY)
    tax_total: Mapped[Decimal | None] = mapped_column(MONEY)
    # The extraction run currently in use; null only for rows written directly by fixtures (B1).
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Unsaved review edits, kept on the server, never in the browser (schema.md 3.4).
    review_draft: Mapped[dict | None] = mapped_column(JSONB)
    # Provenance of header fields: per field ``read`` or ``edited``, by whom, original value (B3).
    field_sources: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # The clerk's note when confirming a document whose own figures do not add up (S-07; B9).
    inconsistent_note: Mapped[str | None] = mapped_column(Text)


class InvoiceLineRow(TenantMixin, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "invoice_id", "line_no"),
        tfk("invoice_id", "invoices"),
        CheckConstraint(enum_check("line_kind", ("item", "freight", "fee", "discount")), name="line_kind"),
        CheckConstraint("(removed_at is null) = (removed_by is null)", name="removed_pair"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    supplier_item_code: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    page_no: Mapped[int | None] = mapped_column(Integer)
    qty: Mapped[Decimal | None] = mapped_column(QTY)
    uom: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal | None] = mapped_column(PRICE)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    line_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="item")
    field_sources: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Soft removal in extraction review (S-07; B9): the row and its earlier results stay as history;
    # a removed line is never matched, counted or shown as a live line.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    removed_reason: Mapped[str | None] = mapped_column(Text)


class UsageEvent(TenantMixin, Base):
    """One billable unit per invoice or credit note, in the month (Pacific time) it was first
    extracted; never twice however often it is re-extracted or re-matched (schema.md 3.3; IT-26)."""

    __tablename__ = "usage_events"
    __table_args__ = tenant_args(
        tfk("invoice_id", "invoices"),
        tfk("document_id", "documents"),
        UniqueConstraint("tenant_id", "invoice_id"),
        Index("ix_usage_events_tenant_id_unit_month", "tenant_id", "unit_month"),
        CheckConstraint(enum_check("kind", ("invoice", "credit_note")), name="kind"),
        CheckConstraint("extract(day from unit_month) = 1", name="first_of_month"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    unit_month: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)


class IntakeSender(TenantMixin, Base):
    """An address or a whole domain allowed to email invoices to the account (schema.md 3.3)."""

    __tablename__ = "intake_senders"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "address_or_domain"))
    address_or_domain: Mapped[str] = mapped_column(CITEXT, nullable=False)
    added_by: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)


INBOUND_STATES = ("processed", "held", "discarded")


class InboundMessage(TenantMixin, Base):
    """An emailed invoice message. From an allowed sender its attachments go into an intake batch;
    otherwise it is held for a person (schema.md 3.3; B7, T-3.3.4)."""

    __tablename__ = "inbound_messages"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "provider_message_id"),
        tfk("raw_document_id", "documents"),
        tfk("batch_id", "upload_batches"),
        CheckConstraint(enum_check("status", INBOUND_STATES), name="status"),
    )
    provider_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    from_address: Mapped[str] = mapped_column(CITEXT, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    raw_document_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
