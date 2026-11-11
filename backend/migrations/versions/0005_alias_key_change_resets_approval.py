"""An alias whose supplier, supplier item code or description changes loses its approval (MH-10; round-3 observation).

Adds `item_aliases.supplier_description` (already in the schema.md dictionary) and extends the trigger of
migration 0004 so that a change of `vendor_id`, `supplier_item_code`, `supplier_item_code_norm` or
`supplier_description` is treated like a change of the conversion: approval cleared, version incremented, a
converting alias back to `pending_approval`.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column("item_aliases", sa.Column("supplier_description", sa.Text(), nullable=True))
    op.execute(
        """
        create or replace function item_aliases_reset_approval() returns trigger language plpgsql as $$
        begin
          if new.conversion_factor is distinct from old.conversion_factor
             or upper(trim(coalesce(new.supplier_uom, ''))) is distinct from upper(trim(coalesce(old.supplier_uom, '')))
             or upper(trim(coalesce(new.item_uom, ''))) is distinct from upper(trim(coalesce(old.item_uom, '')))
             or new.item_id is distinct from old.item_id
             or new.vendor_id is distinct from old.vendor_id
             or new.supplier_item_code is distinct from old.supplier_item_code
             or new.supplier_item_code_norm is distinct from old.supplier_item_code_norm
             or new.supplier_description is distinct from old.supplier_description then
            new.approved_by := null;
            new.version := old.version + 1;
            if new.status = 'active' and (
                 new.conversion_factor <> 1
                 or (new.supplier_uom is not null and new.item_uom is not null
                     and upper(trim(new.supplier_uom)) <> upper(trim(new.item_uom)))) then
              new.status := 'pending_approval';
            end if;
          end if;
          return new;
        end $$;
        """
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
