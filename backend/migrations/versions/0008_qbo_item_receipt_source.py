"""C1 (2026-11-11): QuickBooks Online item-receipt exports as a receiving source.

- ``receiving_imports.source_type`` admits ``qbo_item_receipt_export`` (a report or CSV export;
  the QuickBooks Online Accounting API has no ItemReceipt entity).
- Check ``qbo_item_receipt_class_a``: such an import is always evidence class A; rows that fail the
  independence rule (``receiving.item_receipt_rejection``) are rejected rows, never receipt lines.

Both constraints are added NOT VALID and then validated (schema.md section 9).

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("alter table receiving_imports drop constraint ck_receiving_imports_source_type")
    op.execute(
        "alter table receiving_imports add constraint ck_receiving_imports_source_type check "
        "(source_type in ('spreadsheet', 'delivery_document', 'qbo_item_receipt_export')) not valid"
    )
    op.execute("alter table receiving_imports validate constraint ck_receiving_imports_source_type")
    op.execute(
        "alter table receiving_imports add constraint ck_receiving_imports_qbo_item_receipt_class_a check "
        "(source_type <> 'qbo_item_receipt_export' or evidence_class = 'A') not valid"
    )
    op.execute(
        "alter table receiving_imports validate constraint ck_receiving_imports_qbo_item_receipt_class_a"
    )


def downgrade() -> None:
    raise NotImplementedError("no down-migrations (schema.md section 9)")
