"""Local read-only copies of QuickBooks records (schema.md 3.2). Nothing is ever written back."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy.db import Base, TenantMixin, tenant_args, tfk
from matchdesk.tenancy.types import MONEY, PRICE, QTY, UUIDT, enum_check


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
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
