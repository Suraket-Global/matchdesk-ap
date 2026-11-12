"""B3 (2026-11-12): QuickBooks connection, OAuth states and sync runs (T-3.1.1, T-3.1.2; schema.md 3.2).

- ``qbo_connections``: sealed tokens (AES-256-GCM with key id), erased at disconnect (checks
  ``tokens_while_connected`` and ``tokens_erased_on_disconnect``), ``delete_after`` for the
  QuickBooks-derived rows (self-check 6.4).
- ``qbo_oauth_states``: single-use ``state`` bound to the requesting session.
- ``sync_runs``: cursor per record type, partial unique scope while pending.
- Read-copy columns: purchase-order total and sync token, bill balance, the PO link of bill lines.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

APP_ROLE = "matchdesk_app"
POLICY = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
NEW_TENANT_TABLES = ("qbo_connections", "qbo_oauth_states", "sync_runs")


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.create_table(
        "qbo_connections",
        sa.Column("realm_id", sa.Text(), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.LargeBinary(), nullable=True),
        sa.Column("access_token_enc", sa.LargeBinary(), nullable=True),
        sa.Column("token_key_id", sa.Text(), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes_granted", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("connected_by", sa.UUID(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status <> 'disconnected' or (refresh_token_enc is null and access_token_enc is null)",
            name=op.f("ck_qbo_connections_tokens_erased_on_disconnect"),
        ),
        sa.CheckConstraint(
            "status = 'disconnected' or refresh_token_enc is not null",
            name=op.f("ck_qbo_connections_tokens_while_connected"),
        ),
        sa.CheckConstraint(
            "status in ('connected', 'needs_reconnect', 'disconnected')",
            name=op.f("ck_qbo_connections_status"),
        ),
        sa.ForeignKeyConstraint(
            ["connected_by"], ["users.id"], name=op.f("fk_qbo_connections_connected_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_qbo_connections_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qbo_connections")),
        sa.UniqueConstraint("realm_id", name=op.f("uq_qbo_connections_realm_id")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_qbo_connections_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_qbo_connections_tenant_id")),
    )
    op.create_table(
        "qbo_oauth_states",
        sa.Column("state_hash", sa.LargeBinary(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_qbo_oauth_states_tenant_id_tenants")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_qbo_oauth_states_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qbo_oauth_states")),
        sa.UniqueConstraint("state_hash", name=op.f("uq_qbo_oauth_states_state_hash")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_qbo_oauth_states_tenant_id_id")),
    )
    op.create_table(
        "sync_runs",
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=True),
        sa.Column("range_end", sa.Date(), nullable=True),
        sa.Column("po_references", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("state", sa.Text(), server_default="queued", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cursor", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("scope_fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "mode <> 'date_range' or (range_start is not null and range_end is not null)",
            name=op.f("ck_sync_runs_range_set"),
        ),
        sa.CheckConstraint("mode in ('date_range', 'po_references')", name=op.f("ck_sync_runs_mode")),
        sa.CheckConstraint(
            "state in ('queued', 'running', 'succeeded', 'retry_wait', 'failed')",
            name=op.f("ck_sync_runs_state"),
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_sync_runs_requested_by_users")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_sync_runs_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_sync_runs_tenant_id_id")),
    )
    op.create_index(
        "uq_sync_runs_pending_scope",
        "sync_runs",
        ["tenant_id", "scope_fingerprint"],
        unique=True,
        postgresql_where="state in ('queued', 'running', 'retry_wait')",
    )
    op.add_column("purchase_orders", sa.Column("total", sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column("purchase_orders", sa.Column("qbo_sync_token", sa.Text(), nullable=True))
    op.add_column("qbo_bill_lines", sa.Column("linked_po_qbo_id", sa.Text(), nullable=True))
    op.add_column("qbo_bill_lines", sa.Column("linked_po_line_qbo_id", sa.Text(), nullable=True))
    op.add_column("qbo_bills", sa.Column("balance", sa.Numeric(precision=14, scale=2), nullable=True))
    for table in NEW_TENANT_TABLES:
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
        op.execute(f"create policy tenant_isolation on {table} using ({POLICY}) with check ({POLICY})")
        op.execute(f"grant select, insert, update, delete on {table} to {APP_ROLE}")


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
