"""B11: QuickBooks mode per tenant.

``tenants.qbo_mode text null``: null follows the server setting ``MATCHDESK_QBO_MODE`` (the recorded
demo); ``intuit`` makes this one tenant connect to Intuit (the sandbox locally) while the demo tenant
keeps its recorded responses. Check ``qbo_mode`` added NOT VALID, then validated. ``tenants`` has one
row per account, so the lock lasts milliseconds under the 5-second lock timeout.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column("tenants", sa.Column("qbo_mode", sa.Text(), nullable=True))
    op.execute(
        "alter table tenants add constraint ck_tenants_qbo_mode "
        "check (qbo_mode is null or qbo_mode in ('recorded', 'intuit')) not valid"
    )
    op.execute("alter table tenants validate constraint ck_tenants_qbo_mode")


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
