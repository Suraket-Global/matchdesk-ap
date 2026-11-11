"""An alias whose conversion, units or item change loses its approval (MH-10; round-2 observation).

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create function item_aliases_reset_approval() returns trigger language plpgsql as $$
        begin
          if new.conversion_factor is distinct from old.conversion_factor
             or upper(trim(coalesce(new.supplier_uom, ''))) is distinct from upper(trim(coalesce(old.supplier_uom, '')))
             or upper(trim(coalesce(new.item_uom, ''))) is distinct from upper(trim(coalesce(old.item_uom, '')))
             or new.item_id is distinct from old.item_id then
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
    op.execute(
        "create trigger item_aliases_reset_approval before update on item_aliases "
        "for each row execute function item_aliases_reset_approval()"
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
