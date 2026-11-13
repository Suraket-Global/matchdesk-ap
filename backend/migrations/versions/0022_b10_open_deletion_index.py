"""B10: one open deletion request per account also while it is being deleted.

``uq_deletion_requests_open`` (0018) covered ``requested`` and ``scheduled``; 0020 added the
``deleting`` state, which the code already treats as open (``OPEN_DELETION``). The index now covers
it too, so the database refuses a second request while the worker is removing files.
"""

from __future__ import annotations

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_deletion_requests_open", table_name="deletion_requests")
    op.create_index(
        "uq_deletion_requests_open",
        "deletion_requests",
        ["tenant_id"],
        unique=True,
        postgresql_where="status in ('requested', 'scheduled', 'deleting')",
    )


def downgrade() -> None:
    op.drop_index("uq_deletion_requests_open", table_name="deletion_requests")
    op.create_index(
        "uq_deletion_requests_open",
        "deletion_requests",
        ["tenant_id"],
        unique=True,
        postgresql_where="status in ('requested', 'scheduled')",
    )
