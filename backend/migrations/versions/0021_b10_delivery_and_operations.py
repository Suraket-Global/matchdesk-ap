"""B10 (2026-11-13): weekly email delivery per recipient and the scheduled operations record (outside
QA items 5 and 8).

- ``weekly_summary_deliveries`` (tenant): one row per run and recipient, ``pending``, ``sent`` or
  ``failed``, with attempts, the error class and ``sent_at``. "Sent" is written only after the mailer
  accepted the message; a retry sends only to the recipients still pending or failed.
- ``scheduled_operations`` (global, no tenant data): one row per scheduled operation of the worker
  with its last start, success and failure, the error class and the consecutive failures, so S-18
  shows late or failing operations.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

APP_ROLE = "matchdesk_app"
POLICY = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "weekly_summary_deliveries",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("recipient", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "state in ('pending', 'sent', 'failed')", name=op.f("ck_weekly_summary_deliveries_state")
        ),
        sa.CheckConstraint(
            "(state = 'sent') = (sent_at is not null)",
            name=op.f("ck_weekly_summary_deliveries_sent_has_time"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["weekly_summary_runs.tenant_id", "weekly_summary_runs.id"],
            name=op.f("fk_weekly_summary_deliveries_tenant_id_run_id_weekly_summary_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_weekly_summary_deliveries_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_summary_deliveries")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_weekly_summary_deliveries_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "recipient",
            name=op.f("uq_weekly_summary_deliveries_tenant_id_run_id_recipient"),
        ),
    )
    op.execute("alter table weekly_summary_deliveries enable row level security")
    op.execute("alter table weekly_summary_deliveries force row level security")
    op.execute(
        f"create policy tenant_isolation on weekly_summary_deliveries using ({POLICY}) with check ({POLICY})"
    )
    op.execute(f"grant select, insert, update on weekly_summary_deliveries to {APP_ROLE}")

    op.create_table(
        "scheduled_operations",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_result", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_operations")),
        sa.UniqueConstraint("name", name=op.f("uq_scheduled_operations_name")),
    )
    op.execute(f"grant select, insert, update on scheduled_operations to {APP_ROLE}")


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
