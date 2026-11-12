"""B9 (2026-11-13): index for the S-08 assignee filter, built concurrently (schema.md section 9, R-11).

``exceptions (tenant_id, assigned_to, status)`` as listed in schema.md section 6. One index per
migration, outside the migration transaction.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "create index concurrently if not exists ix_exceptions_tenant_id_assigned_to_status "
            "on exceptions (tenant_id, assigned_to, status)"
        )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
