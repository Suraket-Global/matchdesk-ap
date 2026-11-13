"""B11: the bills a QuickBooks purchase order names (T-1.1.1, observed 2026-11-13).

The sandbox showed the link between a purchase order and its bill only on the purchase order's
own ``LinkedTxn`` (``TxnType = 'Bill'``); the bill and its lines carried no link back.
``purchase_orders.linked_bill_qbo_ids text[] not null default '{}'`` keeps that list, so the sync can
attribute a bill line to a PO line by its item when exactly one line fits, and matching can treat a
linked bill line that fits no single PO line as unknown history on that PO (TRD 8.5, B1-002).
Adding a column with a constant default rewrites nothing; lock timeout 5 seconds.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column(
        "purchase_orders",
        sa.Column(
            "linked_bill_qbo_ids",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
