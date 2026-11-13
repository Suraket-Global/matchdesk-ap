"""B12 (2026-11-13): delete a single document (S-06, S-07).

- ``documents.removed_at``, ``removed_by``, ``removed_reason`` (check ``removed_pair``): a soft
  deletion by a person. The row and the original file stay until the retention rules of schema.md
  section 8 remove them (account deletion; the archive lists the document as deleted). Every match
  input, count, list and report reads live documents only. ``deleted_at`` keeps its meaning (the file
  itself was removed).
- ``uq_documents_tenant_invoice_sha`` also excludes removed documents, so the right copy of a file
  deleted by mistake can be uploaded again.
- ``exception_events.event`` admits ``document_removed``: the exceptions of a deleted document are
  closed with that event; nothing is overwritten. ``match_runs.trigger`` admits
  ``document_removed`` (the re-match of the suppliers' other documents).

Constraints on an existing table are added ``NOT VALID`` and validated (schema.md section 9). The
index is rebuilt in place: ``documents`` holds a few thousand rows per pilot account, so the lock
lasts milliseconds under the 5-second lock timeout.

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

EVENTS = (
    "raised",
    "assigned",
    "resolved",
    "sent_for_approval",
    "approved",
    "returned",
    "withdrawn",
    "reopened",
    "variance_changed",
    "auto_closed",
    "credit_decided",
    "document_removed",
)


TRIGGERS = (
    "document_ready",
    "receiving_import",
    "alias_change",
    "tolerance_change",
    "credit_note",
    "po_change",
    "duplicate_decision",
    "late_receipt_approval",
    "manual",
    "document_removed",
)


def _check(table: str, name: str, expr: str) -> None:
    op.execute(f"alter table {table} add constraint {name} check ({expr}) not valid")
    op.execute(f"alter table {table} validate constraint {name}")


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column("documents", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("removed_by", sa.UUID(), nullable=True))
    op.add_column("documents", sa.Column("removed_reason", sa.Text(), nullable=True))
    op.execute(
        "alter table documents add constraint fk_documents_removed_by_users "
        "foreign key (removed_by) references users (id) not valid"
    )
    op.execute("alter table documents validate constraint fk_documents_removed_by_users")
    _check("documents", "ck_documents_removed_pair", "(removed_at is null) = (removed_by is null)")
    op.drop_index("uq_documents_tenant_invoice_sha", table_name="documents")
    op.create_index(
        "uq_documents_tenant_invoice_sha",
        "documents",
        ["tenant_id", "sha256"],
        unique=True,
        postgresql_where=(
            "purpose = 'invoice' and state <> 'duplicate_file' and deleted_at is null and removed_at is null"
        ),
    )
    events = ", ".join(f"'{e}'" for e in EVENTS)
    op.execute("alter table exception_events drop constraint ck_exception_events_event")
    _check("exception_events", "ck_exception_events_event", f"event in ({events})")
    triggers = ", ".join(f"'{e}'" for e in TRIGGERS)
    op.execute("alter table match_runs drop constraint ck_match_runs_trigger")
    _check("match_runs", "ck_match_runs_trigger", f"trigger in ({triggers})")


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
