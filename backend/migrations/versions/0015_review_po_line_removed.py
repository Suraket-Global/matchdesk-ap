"""B3/B4 review fixes (2026-11-12), finding m6: a purchase-order line deleted in QuickBooks.

``po_lines.removed_at``: set by a sync when a purchase order is read again without the line; such a
line is no longer matched against, imported into or counted. The row is kept for history and earlier
results; the value clears if the line comes back.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column("po_lines", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
