"""B16 (2026-11-17): the pilot fee and the refund threshold in the account's currency.

- ``pilot_engagements.currency`` (ISO 4217 code, three capitals; default ``CAD``): the currency of
  the fee (``price``) and of the refund threshold, which equals the fee (Decision.md 5.1). Every
  record before B16 was CAD 500 by decision (Decision.md section 5), so the default keeps it valid.
  The code sets it to the account's currency on every save (``reporting.save_pilot``).
- ``backtest_reports.currency`` (nullable; same check): the currency of the report's figures,
  stored with the version when it is drafted. Null on versions drafted before B16; they are read in
  the account's currency (``reporting.report_currency``). No backfill: an approved version keeps
  every figure it was approved with, and the whole-row immutability trigger stays as it is.
- ``pilot_governing_set_once`` also refuses a change of ``price`` or ``currency`` once the
  governing version is set, as it already did for ``refund_threshold``.

Columns with a constant default on existing tables are catalogue changes only (no rewrite); the
checks are added not valid, then validated.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column(
        "pilot_engagements",
        sa.Column("currency", sa.String(3), nullable=False, server_default="CAD"),
    )
    op.add_column("backtest_reports", sa.Column("currency", sa.String(3), nullable=True))
    op.execute(
        "alter table pilot_engagements add constraint ck_pilot_engagements_currency_code "
        "check (currency ~ '^[A-Z]{3}$') not valid"
    )
    op.execute("alter table pilot_engagements validate constraint ck_pilot_engagements_currency_code")
    op.execute(
        "alter table backtest_reports add constraint ck_backtest_reports_currency_code "
        "check (currency is null or currency ~ '^[A-Z]{3}$') not valid"
    )
    op.execute("alter table backtest_reports validate constraint ck_backtest_reports_currency_code")
    op.execute(
        """
        create or replace function pilot_governing_set_once() returns trigger language plpgsql as $$
        begin
          if old.governing_report_id is not null and (
               new.governing_report_id is distinct from old.governing_report_id
            or new.refund_qualifying_amount is distinct from old.refund_qualifying_amount
            or new.refund_due is distinct from old.refund_due
            or new.refund_determined_at is distinct from old.refund_determined_at
            or new.refund_threshold is distinct from old.refund_threshold
            or new.price is distinct from old.price
            or new.currency is distinct from old.currency) then
            raise exception 'the governing report version and its refund result are set once'
              using errcode = 'check_violation';
          end if;
          return new;
        end $$;
        """
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
