"""Back-test reports and their frozen findings (schema.md 3.6; T-5.1.1, T-5.1.2; B3).

``report_findings`` is insert-only; a trigger refuses any change to ``totals`` and the amount columns
of an approved report (migration 0013), so an approved version is immutable and a correction is a
new version that supersedes it.
"""

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
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy import MONEY, UUIDT, Base, TenantMixin, enum_check, tenant_args, tfk

REPORT_STATES = ("generating", "draft", "approved", "superseded")
SECTIONS = ("finding", "not_received", "unverified", "waived", "open")
PCT = Numeric(5, 2, asdecimal=True)


class BacktestReport(TenantMixin, Base):
    __tablename__ = "backtest_reports"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "period_start", "period_end", "version_no"),
        CheckConstraint(enum_check("status", REPORT_STATES), name="status"),
        CheckConstraint("period_end >= period_start", name="period_order"),
        CheckConstraint(
            "status <> 'approved' or (approved_by is not null and approved_at is not null)",
            name="approved_has_approver",
        ),
        Index(
            "uq_backtest_reports_approved_period",
            "tenant_id",
            "period_start",
            "period_end",
            unique=True,
            postgresql_where="status = 'approved'",
        ),
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    data_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    totals: Mapped[dict] = mapped_column(JSONB, nullable=False)
    history_read_from: Mapped[date | None] = mapped_column(Date)
    receipt_coverage_pct: Mapped[Decimal | None] = mapped_column(PCT)
    coverage_class_a_pct: Mapped[Decimal | None] = mapped_column(PCT)
    coverage_class_b_pct: Mapped[Decimal | None] = mapped_column(PCT)
    class_c_only_lines: Mapped[int | None] = mapped_column(Integer)
    not_received_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    unverified_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    findings_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    # Sum over exceptions marked ``qualifying``: the only figure the refund criterion uses.
    qualifying_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_report_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)


class ReportFinding(TenantMixin, Base):
    """Insert-only frozen row. A row in section ``finding`` or ``not_received`` of the governing report
    is a flagged discrepancy (PRD M-3a)."""

    __tablename__ = "report_findings"
    __table_args__ = tenant_args(
        tfk("report_id", "backtest_reports"),
        tfk("exception_id", "exceptions"),
        CheckConstraint(enum_check("section", SECTIONS), name="section"),
    )
    report_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    exception_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    section: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    qualifying: Mapped[bool] = mapped_column(Boolean, nullable=False)
    paid_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
