"""Trial guidance (owner, 2026-11-19): the in-app tour and the trial reminder emails.

- ``users.tour_state`` ('done' or 'skipped', null until then) and ``users.tour_state_at``: whether
  the person finished or skipped the guided tour, kept on the server (the app keeps nothing in
  browser storage, App-flow 4.3), so the tour is offered once per person on any device.
- ``tenants.trial_nudges`` (JSON list, default empty): which trial reminder emails ('day1', 'day3',
  'day6') the account has been sent, so each goes once.

Columns with a constant default or nullable are catalogue changes only.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column("users", sa.Column("tour_state", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("tour_state_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "alter table users add constraint ck_users_tour_state "
        "check (tour_state is null or tour_state in ('done', 'skipped')) not valid"
    )
    op.execute("alter table users validate constraint ck_users_tour_state")
    op.add_column(
        "tenants",
        sa.Column("trial_nudges", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
