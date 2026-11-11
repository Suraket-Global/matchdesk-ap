"""Security fixes after the B2 review, round 1 (B2-S01, B2-S02, B2-S06).

- ``login_tokens.totp_failures``: wrong one-time codes per link; the link is burned at the limit.
- ``auth_rate_events.kind`` admits ``totp_fail_user`` (wrong codes per account).
- Rate-limit keys become HMACs under a server key; the old unkeyed rows are disposable counters and
  are deleted. ``login_tokens.requested_ip`` is no longer written; existing values are cleared (the
  column is dropped in a later contract migration).
- Trigger ``sessions_operator_no_tenant``: a session of an operator never carries a tenant (operators
  enter a tenant only through a support grant, not built yet).

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column(
        "login_tokens", sa.Column("totp_failures", sa.Integer(), server_default="0", nullable=False)
    )
    op.execute("update login_tokens set requested_ip = null")
    op.execute("delete from auth_rate_events")
    op.execute("alter table auth_rate_events drop constraint ck_auth_rate_events_kind")
    op.execute(
        "alter table auth_rate_events add constraint ck_auth_rate_events_kind check "
        "(kind in ('link_address', 'link_ip', 'exchange_fail_ip', 'totp_fail_user'))"
    )
    op.execute(
        """
        create function sessions_operator_no_tenant() returns trigger language plpgsql as $$
        begin
          if new.active_tenant_id is not null
             and exists (select 1 from users u where u.id = new.user_id and u.is_operator) then
            raise exception 'an operator session cannot carry a tenant without a support grant'
              using errcode = 'check_violation';
          end if;
          return new;
        end $$;
        """
    )
    op.execute(
        "create trigger sessions_operator_no_tenant before insert or update on sessions "
        "for each row execute function sessions_operator_no_tenant()"
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
