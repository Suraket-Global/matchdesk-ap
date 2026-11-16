"""B14 (2026-11-17, acceptance M3): files an intake batch refused stay visible with the reason.

``upload_batches.refused_files`` (JSON list, default empty): one entry per file the server refused
before storing it (not a PDF or image, empty, larger than the limit), with the name the person or
the sender gave it, the reason code, the size and the time. The file itself is never stored: it
failed the content check of TRD 8.7. The batch can then say how many files were chosen and never
claims that every file was read.

A column with a constant default on an existing table is a catalogue change only (no rewrite).

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column(
        "upload_batches",
        sa.Column("refused_files", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
