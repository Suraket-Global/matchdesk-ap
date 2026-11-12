"""B3 (2026-11-12): receiving imports, mappings, attestation and approvals (T-3.2.1, T-3.2.2, T-4.2.3; schema.md 3.3, 3.6).

- ``receiving_imports``: who keeps the log, mapping in effect, row counts and rejected rows with
  reasons, who committed or voided and why, draft expiry.
- ``receipts``: receiver reference, page, who confirmed a class B delivery document and when.
- ``receiving_mappings`` (saved column mappings) and ``receiving_attestations`` (insert-only: the
  controller attests the evidence class and the accounts-payable users of the item-receipt rule).
- ``approvals``: waiver, alias conversion or late receiving evidence; exactly one subject; one
  pending approval per subject.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

APP_ROLE = "matchdesk_app"
POLICY = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
NEW_TENANT_TABLES: dict[str, str] = {
    "receiving_mappings": "select, insert, update, delete",
    "receiving_attestations": "select, insert",
    "approvals": "select, insert, update",
}


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.create_table(
        "receiving_attestations",
        sa.Column("evidence_class", sa.Text(), nullable=False),
        sa.Column("source_description", sa.Text(), nullable=False),
        sa.Column("ap_staff", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("attested_by", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "evidence_class in ('A', 'B', 'C')", name=op.f("ck_receiving_attestations_evidence_class")
        ),
        sa.ForeignKeyConstraint(
            ["attested_by"], ["users.id"], name=op.f("fk_receiving_attestations_attested_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_receiving_attestations_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receiving_attestations")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_receiving_attestations_tenant_id_id")),
    )
    op.create_table(
        "receiving_mappings",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_receiving_mappings_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_receiving_mappings_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receiving_mappings")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_receiving_mappings_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_receiving_mappings_tenant_id_name")),
    )
    op.create_table(
        "approvals",
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("exception_id", sa.UUID(), nullable=True),
        sa.Column("alias_id", sa.UUID(), nullable=True),
        sa.Column("receiving_import_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("requested_resolution", sa.Text(), nullable=True),
        sa.Column("requested_note", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("self_approved", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(subject_type = 'waiver') = (exception_id is not null) and (subject_type = 'alias_conversion') = (alias_id is not null) and (subject_type = 'late_receipt') = (receiving_import_id is not null)",
            name=op.f("ck_approvals_subject_matches_type"),
        ),
        sa.CheckConstraint(
            "reason is null or reason in ('above_item_limit', 'above_period_cap')",
            name=op.f("ck_approvals_reason"),
        ),
        sa.CheckConstraint(
            "status in ('pending', 'approved', 'returned', 'withdrawn')", name=op.f("ck_approvals_status")
        ),
        sa.CheckConstraint(
            "subject_type in ('waiver', 'alias_conversion', 'late_receipt')",
            name=op.f("ck_approvals_subject_type"),
        ),
        sa.CheckConstraint(
            "(exception_id is not null)::int + (alias_id is not null)::int + (receiving_import_id is not null)::int = 1",
            name=op.f("ck_approvals_one_subject"),
        ),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_approvals_decided_by_users")),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_approvals_requested_by_users")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "alias_id"],
            ["item_aliases.tenant_id", "item_aliases.id"],
            name=op.f("fk_approvals_tenant_id_alias_id_item_aliases"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exception_id"],
            ["exceptions.tenant_id", "exceptions.id"],
            name=op.f("fk_approvals_tenant_id_exception_id_exceptions"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "receiving_import_id"],
            ["receiving_imports.tenant_id", "receiving_imports.id"],
            name=op.f("fk_approvals_tenant_id_receiving_import_id_receiving_imports"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_approvals_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_approvals_tenant_id_id")),
    )
    op.create_index(
        "uq_approvals_pending_alias",
        "approvals",
        ["tenant_id", "alias_id"],
        unique=True,
        postgresql_where="status = 'pending' and alias_id is not null",
    )
    op.create_index(
        "uq_approvals_pending_exception",
        "approvals",
        ["tenant_id", "exception_id"],
        unique=True,
        postgresql_where="status = 'pending' and exception_id is not null",
    )
    op.create_index(
        "uq_approvals_pending_import",
        "approvals",
        ["tenant_id", "receiving_import_id"],
        unique=True,
        postgresql_where="status = 'pending' and receiving_import_id is not null",
    )
    op.add_column("receipts", sa.Column("receiver_ref", sa.Text(), nullable=True))
    op.add_column("receipts", sa.Column("source_page", sa.Integer(), nullable=True))
    op.add_column("receipts", sa.Column("confirmed_by", sa.UUID(), nullable=True))
    op.add_column("receipts", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_receipts_confirmed_by_users"), "receipts", "users", ["confirmed_by"], ["id"]
    )
    op.add_column("receiving_imports", sa.Column("kept_by_name", sa.Text(), nullable=True))
    op.add_column("receiving_imports", sa.Column("mapping_id", sa.UUID(), nullable=True))
    op.add_column(
        "receiving_imports", sa.Column("column_map", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("receiving_imports", sa.Column("rows_total", sa.Integer(), nullable=True))
    op.add_column("receiving_imports", sa.Column("rows_valid", sa.Integer(), nullable=True))
    op.add_column("receiving_imports", sa.Column("rows_rejected", sa.Integer(), nullable=True))
    op.add_column(
        "receiving_imports",
        sa.Column("rejected_rows", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("receiving_imports", sa.Column("created_by", sa.UUID(), nullable=True))
    op.add_column("receiving_imports", sa.Column("committed_by", sa.UUID(), nullable=True))
    op.add_column("receiving_imports", sa.Column("voided_by", sa.UUID(), nullable=True))
    op.add_column("receiving_imports", sa.Column("void_reason", sa.Text(), nullable=True))
    op.add_column("receiving_imports", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_receiving_imports_tenant_id_mapping_id_receiving_mappings"),
        "receiving_imports",
        "receiving_mappings",
        ["tenant_id", "mapping_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        op.f("fk_receiving_imports_created_by_users"), "receiving_imports", "users", ["created_by"], ["id"]
    )
    op.create_foreign_key(
        op.f("fk_receiving_imports_committed_by_users"),
        "receiving_imports",
        "users",
        ["committed_by"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_receiving_imports_voided_by_users"), "receiving_imports", "users", ["voided_by"], ["id"]
    )
    for table, rights in NEW_TENANT_TABLES.items():
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
        op.execute(f"create policy tenant_isolation on {table} using ({POLICY}) with check ({POLICY})")
        op.execute(f"grant {rights} on {table} to {APP_ROLE}")
    op.execute(
        "create trigger receiving_attestations_insert_only before update or delete on receiving_attestations "
        "for each statement execute function refuse_change()"
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
