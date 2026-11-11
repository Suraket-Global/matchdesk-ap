"""Match runs unique on input fingerprint only while pending (B1-001); converting aliases need approval (B1-008).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.drop_constraint("uq_match_runs_tenant_id_input_fingerprint", "match_runs", type_="unique")
    op.create_index("ix_match_runs_tenant_fingerprint", "match_runs", ["tenant_id", "input_fingerprint"])
    op.create_index(
        "uq_match_runs_pending_fingerprint",
        "match_runs",
        ["tenant_id", "input_fingerprint"],
        unique=True,
        postgresql_where="state in ('queued', 'running', 'retry_wait')",
    )

    # Pre-release: the tables are empty in every environment, so plain index builds are used here;
    # from the first production deploy, indexes on existing tables follow schema.md section 9.
    op.execute("alter table item_aliases drop constraint ck_item_aliases_conversion_needs_approval")
    op.execute(
        "alter table item_aliases add constraint ck_item_aliases_conversion_needs_approval check ("
        "not (status = 'active' and (conversion_factor <> 1 or (supplier_uom is not null and item_uom is not null and upper(trim(supplier_uom)) <> upper(trim(item_uom))))) or approved_by is not null) not valid"
    )
    op.execute("alter table item_aliases validate constraint ck_item_aliases_conversion_needs_approval")


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
