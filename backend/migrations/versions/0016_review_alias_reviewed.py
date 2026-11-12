"""B3/B4 review fixes (2026-11-12), finding W5: "Mark reviewed" on new 1-to-1 aliases.

``item_aliases.reviewed_by`` and ``reviewed_at``: set when the controller acknowledges a new 1-to-1
alias on S-12, so the list of aliases waiting for review empties. Before this, the acknowledgement
was only an audit event and the same aliases stayed listed.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column("item_aliases", sa.Column("reviewed_by", sa.UUID(), nullable=True))
    op.add_column("item_aliases", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_item_aliases_reviewed_by_users"), "item_aliases", "users", ["reviewed_by"], ["id"]
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
