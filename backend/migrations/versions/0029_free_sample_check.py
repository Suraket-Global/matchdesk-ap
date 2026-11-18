"""Free sample check (owner, 2026-11-18): a new account can start on a free sample of one month.

- ``tenants.status`` gains 'sample' (before 'pilot'); the operator starts the pilot, which moves it
  to 'pilot' and lifts the sample's limits (``tenancy.sample``).
- ``tenants.sample_ends_at`` (nullable): the end of the sample, 7 days after the account is created.
  Kept after the pilot starts, as history.

Existing accounts are unchanged (all 'pilot', no end). The check is replaced not valid, then
validated.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column("tenants", sa.Column("sample_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("alter table tenants drop constraint ck_tenants_status")
    op.execute(
        "alter table tenants add constraint ck_tenants_status "
        "check (status in ('sample', 'pilot', 'active', 'ended')) not valid"
    )
    op.execute("alter table tenants validate constraint ck_tenants_status")


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
