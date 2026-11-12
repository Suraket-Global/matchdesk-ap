"""B3 (2026-11-12): exception workflow settings (T-4.2.3, T-4.2.4, T-4.1.1 (d); schema.md 3.1, 3.5).

- ``tenants.waiver_limit`` (default 100.00) and ``waiver_period_cap`` (default 500.00), both
  [assumption] defaults of PRD MH-11; check ``waiver_limits`` (cap at least the limit), added NOT VALID
  then validated.
- ``item_aliases.retire_reason``.
- Extension ``pg_trgm`` for alias suggestions by description similarity (no index yet: an index on
  the existing ``items`` table is built concurrently in its own migration when volume needs it).

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("create extension if not exists pg_trgm")
    op.add_column("item_aliases", sa.Column("retire_reason", sa.Text(), nullable=True))
    op.add_column(
        "tenants",
        sa.Column("waiver_limit", sa.Numeric(precision=14, scale=2), server_default="100.00", nullable=False),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "waiver_period_cap", sa.Numeric(precision=14, scale=2), server_default="500.00", nullable=False
        ),
    )
    op.execute(
        "alter table tenants add constraint ck_tenants_waiver_limits "
        "check (waiver_limit >= 0 and waiver_period_cap >= waiver_limit) not valid"
    )
    op.execute("alter table tenants validate constraint ck_tenants_waiver_limits")


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
