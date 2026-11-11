"""Rules, match results and exceptions (schema.md 3.5, 3.6).

``line_matches`` rows are immutable results; the application role may update
only ``is_current`` and ``superseded_by_run_id`` (column grant in the migration).
The check constraints below are the database guard against a coding slip that
would store a pass with no receipt (MH-07, IT-24).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSTZRANGE, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy import (
    MONEY,
    PRICE,
    QTY,
    UUIDT,
    Base,
    GlobalMixin,
    TenantMixin,
    enum_check,
    tenant_args,
    tfk,
)

EXCEPTION_TYPES = (
    "extraction_unverified",
    "duplicate",
    "possible_duplicate",
    "no_po",
    "alias_unconfirmed",
    "po_line_not_found",
    "uom_unresolved",
    "history_incomplete",
    "receipt_absent",
    "qty_over_received",
    "qty_over_ordered",
    "price_variance",
    "unmatched_charge",
    "credit_unlinked",
    "currency_unsupported",
)
RESOLUTION_CODES = (
    "confirmed_overbilling",
    "confirmed_short_shipment",
    "confirmed_duplicate",
    "confirmed_not_received",
    "not_a_duplicate",
    "waived",
    "source_corrected",
    "resolved_by_credit",
)
MATCH_TRIGGERS = (
    "document_ready",
    "receiving_import",
    "alias_change",
    "tolerance_change",
    "credit_note",
    "po_change",
    "duplicate_decision",
    "late_receipt_approval",
    "manual",
)
RUN_STATES = ("queued", "running", "succeeded", "retry_wait", "failed")


class ItemAlias(TenantMixin, Base):
    __tablename__ = "item_aliases"
    __table_args__ = tenant_args(
        tfk("vendor_id", "vendors"),
        tfk("item_id", "items"),
        CheckConstraint("conversion_factor > 0", name="conversion_positive"),
        CheckConstraint(
            enum_check("status", ("pending_approval", "active", "retired", "returned")), name="status"
        ),
        CheckConstraint(
            # A converting alias (factor not 1, or different units) needs approval (MH-10, B1-008).
            "not (status = 'active' and (conversion_factor <> 1 or (supplier_uom is not null and item_uom is not null "
            "and upper(trim(supplier_uom)) <> upper(trim(item_uom))))) or approved_by is not null",
            name="conversion_needs_approval",
        ),
        Index(
            "uq_item_aliases_live_code",
            "tenant_id",
            "vendor_id",
            "supplier_item_code_norm",
            unique=True,
            postgresql_where="status in ('pending_approval', 'active')",
        ),
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    supplier_item_code: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_item_code_norm: Mapped[str] = mapped_column(Text, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    supplier_uom: Mapped[str | None] = mapped_column(Text)
    item_uom: Mapped[str | None] = mapped_column(Text)
    conversion_factor: Mapped[Decimal] = mapped_column(PRICE, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ToleranceRule(TenantMixin, Base):
    """Append-only tolerance versions. There is no receipt tolerance column, by design (MH-07)."""

    __tablename__ = "tolerance_rules"
    validity = Column(TSTZRANGE, Computed("tstzrange(valid_from, valid_to)", persisted=True))
    __table_args__ = tenant_args(
        tfk("vendor_id", "vendors"),
        CheckConstraint("price_tol_pct between 0 and 10", name="pct_range"),
        CheckConstraint(
            "qty_tolerance >= 0 and price_tol_abs >= 0 and charge_allowance >= 0", name="non_negative"
        ),
        ExcludeConstraint(
            ("tenant_id", "="),
            ("vendor_id", "="),
            ("validity", "&&"),
            where=text("vendor_id is not null"),
            name="ex_tolerance_rules_vendor",
            using="gist",
        ),
        ExcludeConstraint(
            ("tenant_id", "="),
            ("validity", "&&"),
            where=text("vendor_id is null"),
            name="ex_tolerance_rules_default",
            using="gist",
        ),
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    qty_tolerance: Mapped[Decimal] = mapped_column(QTY, nullable=False, server_default="0")
    price_tol_abs: Mapped[Decimal] = mapped_column(PRICE, nullable=False, server_default="0.01")
    price_tol_pct: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default="0.5")
    charge_allowance: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)


class RulesetVersion(GlobalMixin, Base):
    __tablename__ = "ruleset_versions"
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MatchRun(TenantMixin, Base):
    __tablename__ = "match_runs"
    __table_args__ = tenant_args(
        # A finished run is not unique on its inputs: returning to an earlier input state needs a new
        # current run (B1-001). Only one pending run per input fingerprint may exist.
        Index("ix_match_runs_tenant_fingerprint", "tenant_id", "input_fingerprint"),
        Index(
            "uq_match_runs_pending_fingerprint",
            "tenant_id",
            "input_fingerprint",
            unique=True,
            postgresql_where="state in ('queued', 'running', 'retry_wait')",
        ),
        CheckConstraint(enum_check("trigger", MATCH_TRIGGERS), name="trigger"),
        CheckConstraint(enum_check("state", RUN_STATES), name="state"),
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_ref: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ruleset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUIDT, ForeignKey("ruleset_versions.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lines_evaluated: Mapped[int | None] = mapped_column(Integer)
    lines_matched: Mapped[int | None] = mapped_column(Integer)
    exceptions_raised: Mapped[int | None] = mapped_column(Integer)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LineMatch(TenantMixin, Base):
    __tablename__ = "line_matches"
    __table_args__ = tenant_args(
        tfk("match_run_id", "match_runs"),
        tfk("invoice_line_id", "invoice_lines"),
        tfk("po_line_id", "po_lines"),
        tfk("alias_id", "item_aliases"),
        tfk("tolerance_rule_id", "tolerance_rules"),
        tfk("superseded_by_run_id", "match_runs"),
        CheckConstraint(enum_check("line_kind", ("item", "freight", "fee", "discount")), name="line_kind"),
        CheckConstraint(
            enum_check("status", ("matched", "charge_ok", "exception", "not_evaluated")), name="status"
        ),
        CheckConstraint("receipt_line_count >= 0", name="receipt_count_non_negative"),
        # The guard of schema.md 3.5: a pass needs an item line, a counting receipt, a PO line and an alias.
        CheckConstraint(
            "status <> 'matched' or (line_kind = 'item' and receipt_line_count > 0 "
            "and po_line_id is not null and alias_id is not null)",
            name="matched_needs_receipt",
        ),
        CheckConstraint("status <> 'charge_ok' or line_kind <> 'item'", name="charge_ok_kind"),
        Index(
            "uq_line_matches_current",
            "tenant_id",
            "invoice_line_id",
            unique=True,
            postgresql_where="is_current",
        ),
    )
    match_run_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    invoice_line_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    line_kind: Mapped[str] = mapped_column(Text, nullable=False)
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    alias_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    tolerance_rule_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    qty_ordered: Mapped[Decimal | None] = mapped_column(QTY)
    qty_received_cum: Mapped[Decimal | None] = mapped_column(QTY)
    qty_invoiced_cum_net: Mapped[Decimal | None] = mapped_column(QTY)
    qty_invoiced_prior_qbo: Mapped[Decimal | None] = mapped_column(QTY)
    receipt_line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    checks_run: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    covered: Mapped[bool | None] = mapped_column(Boolean)
    po_unit_price: Mapped[Decimal | None] = mapped_column(PRICE)
    invoice_unit_price_po_uom: Mapped[Decimal | None] = mapped_column(PRICE)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    superseded_by_run_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)


class ExceptionRow(TenantMixin, Base):
    __tablename__ = "exceptions"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "fingerprint"),
        tfk("invoice_id", "invoices"),
        tfk("invoice_line_id", "invoice_lines"),
        tfk("line_match_id", "line_matches"),
        tfk("related_invoice_id", "invoices"),
        CheckConstraint(enum_check("type", EXCEPTION_TYPES), name="type"),
        CheckConstraint(
            enum_check("value_class", ("finding_candidate", "open_undecided", "unverified", "none")),
            name="value_class",
        ),
        CheckConstraint(
            enum_check("status", ("open", "pending_approval", "resolved", "waived", "auto_closed")),
            name="status",
        ),
        CheckConstraint(
            "resolution_code is null or " + enum_check("resolution_code", RESOLUTION_CODES),
            name="resolution_code",
        ),
        CheckConstraint("resolution_code <> 'waived' or resolution_note is not null", name="waiver_note"),
        # receipt_absent: never resolved as overbilling or short shipment; a finding only when not received.
        CheckConstraint(
            "type <> 'receipt_absent' or resolution_code is null or resolution_code in "
            "('confirmed_not_received', 'resolved_by_credit', 'source_corrected', 'waived')",
            name="receipt_absent_resolution",
        ),
        CheckConstraint(
            "type <> 'receipt_absent' or value_class <> 'finding_candidate' or "
            "coalesce(sub_reason, '') = 'not_received' or coalesce(resolution_code, '') = 'confirmed_not_received'",
            name="receipt_absent_finding",
        ),
        CheckConstraint(
            "type <> 'receipt_absent' or coalesce(sub_reason, '') in ('not_received', 'supplier_slip_only', 'no_evidence')",
            name="receipt_absent_sub_reason",
        ),
    )
    fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    invoice_line_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    line_match_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    sub_reason: Mapped[str | None] = mapped_column(Text)
    possibly_credited_bill_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    variance_qty: Mapped[Decimal | None] = mapped_column(QTY)
    variance_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    reported_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    value_class: Mapped[str] = mapped_column(Text, nullable=False)
    qualifying: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    related_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    resolution_code: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    label: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ExceptionEvent(TenantMixin, Base):
    """Insert-only history of an exception."""

    __tablename__ = "exception_events"
    __table_args__ = tenant_args(
        tfk("exception_id", "exceptions"),
        tfk("match_run_id", "match_runs"),
        CheckConstraint(
            enum_check(
                "event",
                (
                    "raised",
                    "assigned",
                    "resolved",
                    "sent_for_approval",
                    "approved",
                    "returned",
                    "withdrawn",
                    "reopened",
                    "variance_changed",
                    "auto_closed",
                ),
            ),
            name="event",
        ),
    )
    exception_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    actor_job_id: Mapped[str | None] = mapped_column(Text)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    match_run_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
