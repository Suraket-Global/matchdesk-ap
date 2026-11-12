"""Local read-only copies of QuickBooks records (schema.md 3.2). Nothing is ever written back."""

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

from matchdesk.tenancy import MONEY, PRICE, QTY, UUIDT, Base, TenantMixin, enum_check, tenant_args, tfk


class Vendor(TenantMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "qbo_id"))
    qbo_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Item(TenantMixin, Base):
    __tablename__ = "items"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "qbo_id"))
    qbo_id: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    purchase_uom: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PurchaseOrderRow(TenantMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "qbo_id"), tfk("vendor_id", "vendors"))
    qbo_id: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    po_number: Mapped[str] = mapped_column(Text, nullable=False)
    po_number_norm: Mapped[str] = mapped_column(Text, nullable=False)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    qbo_status: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal | None] = mapped_column(MONEY)
    qbo_sync_token: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PoLineRow(TenantMixin, Base):
    __tablename__ = "po_lines"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "purchase_order_id", "qbo_line_id"),
        tfk("purchase_order_id", "purchase_orders"),
        tfk("item_id", "items"),
        CheckConstraint(
            "charge_kind is null or " + enum_check("charge_kind", ("freight", "fee")), name="charge_kind"
        ),
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    qbo_line_id: Mapped[str] = mapped_column(Text, nullable=False)
    line_no: Mapped[int | None] = mapped_column(Integer)
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    description: Mapped[str | None] = mapped_column(Text)
    qty_ordered: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    uom: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    # Never used as a receipt (AD-05); only for the history_incomplete check.
    qbo_billed_qty: Mapped[Decimal | None] = mapped_column(QTY)
    charge_kind: Mapped[str | None] = mapped_column(Text)
    # Set when a sync reads the purchase order without this line (deleted in QuickBooks; m6).
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QboBillRow(TenantMixin, Base):
    __tablename__ = "qbo_bills"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "txn_type", "qbo_id"),
        tfk("vendor_id", "vendors"),
        CheckConstraint(enum_check("txn_type", ("bill", "vendor_credit")), name="txn_type"),
        CheckConstraint(
            enum_check("paid_status", ("paid", "partly_paid", "unpaid", "unknown")), name="paid_status"
        ),
    )
    qbo_id: Mapped[str] = mapped_column(Text, nullable=False)
    txn_type: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    doc_number: Mapped[str | None] = mapped_column(Text)
    doc_number_norm: Mapped[str | None] = mapped_column(Text)
    txn_date: Mapped[date | None] = mapped_column(Date)
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    balance: Mapped[Decimal | None] = mapped_column(MONEY)
    paid_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    references_invoice_number: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QboBillLineRow(TenantMixin, Base):
    __tablename__ = "qbo_bill_lines"
    __table_args__ = tenant_args(tfk("qbo_bill_id", "qbo_bills"), tfk("po_line_id", "po_lines"))
    qbo_bill_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    qbo_line_id: Mapped[str | None] = mapped_column(Text)
    qty: Mapped[Decimal | None] = mapped_column(QTY)
    unit_price: Mapped[Decimal | None] = mapped_column(PRICE)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    linked_po_qbo_id: Mapped[str | None] = mapped_column(Text)
    linked_po_line_qbo_id: Mapped[str | None] = mapped_column(Text)
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)


CONNECTION_STATES = ("connected", "needs_reconnect", "disconnected")
SYNC_STATES = ("queued", "running", "succeeded", "retry_wait", "failed")


class QboConnection(TenantMixin, Base):
    """One QuickBooks company per tenant (schema.md 3.2). Tokens are AES-256-GCM sealed with a key id
    and erased at disconnect (B3: the token columns become null, check ``tokens_while_connected``)."""

    __tablename__ = "qbo_connections"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id"),
        UniqueConstraint("realm_id"),
        CheckConstraint(enum_check("status", CONNECTION_STATES), name="status"),
        CheckConstraint(
            "status = 'disconnected' or refresh_token_enc is not null", name="tokens_while_connected"
        ),
        CheckConstraint(
            "status <> 'disconnected' or (refresh_token_enc is null and access_token_enc is null)",
            name="tokens_erased_on_disconnect",
        ),
    )
    realm_id: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    access_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    token_key_id: Mapped[str] = mapped_column(Text, nullable=False)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes_granted: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    connected_by: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # QuickBooks-derived rows are deleted on this date after a disconnect (schema.md 8; self-check 6.4).
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class QboOauthState(TenantMixin, Base):
    """A pending authorisation: the hash of the random ``state`` bound to the session that asked
    for it. Single use, ten minutes (B3, T-3.1.1 (a), (b))."""

    __tablename__ = "qbo_oauth_states"
    __table_args__ = tenant_args(UniqueConstraint("state_hash"))
    state_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncRun(TenantMixin, Base):
    __tablename__ = "sync_runs"
    __table_args__ = tenant_args(
        CheckConstraint(enum_check("mode", ("date_range", "po_references")), name="mode"),
        CheckConstraint(enum_check("state", SYNC_STATES), name="state"),
        CheckConstraint(
            "mode <> 'date_range' or (range_start is not null and range_end is not null)", name="range_set"
        ),
        Index(
            "uq_sync_runs_pending_scope",
            "tenant_id",
            "scope_fingerprint",
            unique=True,
            postgresql_where="state in ('queued', 'running', 'retry_wait')",
        ),
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    range_start: Mapped[date | None] = mapped_column(Date)
    range_end: Mapped[date | None] = mapped_column(Date)
    po_references: Mapped[list | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cursor: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    error_code: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    scope_fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


PO_CHANGE_KINDS = ("changed", "removed")


class PoLineChange(TenantMixin, Base):
    """What a QuickBooks read changed or removed on a purchase-order line (S-10 banner; B9).

    Insert-only history written by the sync: the values before and after (ordered quantity, unit,
    unit price, item), never a write to QuickBooks. Affected lines are re-matched by the sync's
    ``po_change`` match request."""

    __tablename__ = "po_line_changes"
    __table_args__ = tenant_args(
        tfk("purchase_order_id", "purchase_orders"),
        tfk("po_line_id", "po_lines"),
        tfk("sync_run_id", "sync_runs"),
        CheckConstraint(enum_check("change", PO_CHANGE_KINDS), name="change"),
        Index(
            "ix_po_line_changes_tenant_id_purchase_order_id_detected_at",
            "tenant_id",
            "purchase_order_id",
            "detected_at",
        ),
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    po_line_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    change: Mapped[str] = mapped_column(Text, nullable=False)
    before: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict | None] = mapped_column(JSONB)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
