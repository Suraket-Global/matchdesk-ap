"""B3 (2026-11-12): extraction results as documents and their review (T-3.3.1, T-3.3.2, T-3.3.3; schema.md 3.4).

- ``documents``: user-supplied name (database only), page count, uploader.
- ``invoices``: vendor name as read, subtotal and tax, the extraction run in use, who confirmed and
  when, the server-side review draft and header-field provenance (``field_sources``).
- ``invoice_lines``: description and page.

All new columns are nullable or have a default, so existing rows need no backfill.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column("documents", sa.Column("original_name", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("uploaded_by", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_uploaded_by_users"), "documents", "users", ["uploaded_by"], ["id"]
    )
    op.add_column("invoice_lines", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("invoice_lines", sa.Column("page_no", sa.Integer(), nullable=True))
    op.add_column("invoices", sa.Column("vendor_name_read", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column("invoices", sa.Column("tax_total", sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column("invoices", sa.Column("extraction_run_id", sa.UUID(), nullable=True))
    op.add_column("invoices", sa.Column("confirmed_by", sa.UUID(), nullable=True))
    op.add_column("invoices", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "invoices", sa.Column("review_draft", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "invoices",
        sa.Column(
            "field_sources", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )
    op.create_foreign_key(
        op.f("fk_invoices_tenant_id_extraction_run_id_extraction_runs"),
        "invoices",
        "extraction_runs",
        ["tenant_id", "extraction_run_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        op.f("fk_invoices_confirmed_by_users"), "invoices", "users", ["confirmed_by"], ["id"]
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
