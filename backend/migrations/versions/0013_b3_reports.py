"""B3 (2026-11-12): back-test reports and frozen findings (T-5.1.1, T-5.1.2; schema.md 3.6).

- ``backtest_reports``: one row per version; one approved version per period (partial unique);
  trigger ``backtest_reports_approved_immutable`` refuses any change to an approved version except
  becoming ``superseded``.
- ``report_findings``: insert-only (grant and trigger).

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

APP_ROLE = "matchdesk_app"
POLICY = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
NEW_TENANT_TABLES: dict[str, str] = {
    "backtest_reports": "select, insert, update",
    "report_findings": "select, insert",
}


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.create_table(
        "backtest_reports",
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("data_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("totals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("history_read_from", sa.Date(), nullable=True),
        sa.Column("receipt_coverage_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("coverage_class_a_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("coverage_class_b_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("class_c_only_lines", sa.Integer(), nullable=True),
        sa.Column("not_received_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("unverified_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("findings_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("qualifying_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("is_stale", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_report_id", sa.UUID(), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status <> 'approved' or (approved_by is not null and approved_at is not null)",
            name=op.f("ck_backtest_reports_approved_has_approver"),
        ),
        sa.CheckConstraint(
            "status in ('generating', 'draft', 'approved', 'superseded')",
            name=op.f("ck_backtest_reports_status"),
        ),
        sa.CheckConstraint("period_end >= period_start", name=op.f("ck_backtest_reports_period_order")),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["users.id"], name=op.f("fk_backtest_reports_approved_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_backtest_reports_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_backtest_reports_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_reports")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_backtest_reports_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "period_start",
            "period_end",
            "version_no",
            name=op.f("uq_backtest_reports_tenant_id_period_start_period_end_version_no"),
        ),
    )
    op.create_index(
        "uq_backtest_reports_approved_period",
        "backtest_reports",
        ["tenant_id", "period_start", "period_end"],
        unique=True,
        postgresql_where="status = 'approved'",
    )
    op.create_table(
        "report_findings",
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("exception_id", sa.UUID(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.UUID(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("qualifying", sa.Boolean(), nullable=False),
        sa.Column("paid_status", sa.Text(), server_default="unknown", nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "section in ('finding', 'not_received', 'unverified', 'waived', 'open')",
            name=op.f("ck_report_findings_section"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exception_id"],
            ["exceptions.tenant_id", "exceptions.id"],
            name=op.f("fk_report_findings_tenant_id_exception_id_exceptions"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "report_id"],
            ["backtest_reports.tenant_id", "backtest_reports.id"],
            name=op.f("fk_report_findings_tenant_id_report_id_backtest_reports"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_report_findings_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_findings")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_report_findings_tenant_id_id")),
    )
    for table, rights in NEW_TENANT_TABLES.items():
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
        op.execute(f"create policy tenant_isolation on {table} using ({POLICY}) with check ({POLICY})")
        op.execute(f"grant {rights} on {table} to {APP_ROLE}")
    op.execute(
        "create trigger report_findings_insert_only before update or delete on report_findings "
        "for each statement execute function refuse_change()"
    )
    op.execute(
        """
        create function backtest_reports_approved_immutable() returns trigger language plpgsql as $$
        begin
          if old.status in ('approved', 'superseded') and old.approved_at is not null and (
               new.totals is distinct from old.totals
            or new.qualifying_amount is distinct from old.qualifying_amount
            or new.findings_amount is distinct from old.findings_amount
            or new.not_received_amount is distinct from old.not_received_amount
            or new.unverified_amount is distinct from old.unverified_amount
            or new.approved_by is distinct from old.approved_by
            or new.approved_at is distinct from old.approved_at
            or new.status not in ('approved', 'superseded')
            or (old.status = 'superseded' and new.status <> 'superseded')) then
            raise exception 'an approved report version is immutable' using errcode = 'check_violation';
          end if;
          return new;
        end $$;
        """
    )
    op.execute(
        "create trigger backtest_reports_approved_immutable before update on backtest_reports "
        "for each row execute function backtest_reports_approved_immutable()"
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
