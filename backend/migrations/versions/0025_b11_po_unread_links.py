"""B11 (lead review, B11-2): transactions a QuickBooks purchase order names that MatchDesk does not read.

``purchase_orders.unread_linked_txns text[] not null default '{}'`` holds ``"<TxnType>:<TxnId>"`` for
each entry of the PO's own ``LinkedTxn`` other than a bill (the sandbox showed a ``Purchase``). Such a
PO's history is unknown, so every line on it is ``history_incomplete`` (TRD 8.5). A constant
default rewrites nothing; lock timeout 5 seconds.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column(
        "purchase_orders",
        sa.Column(
            "unread_linked_txns",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
