"""Sign-in links, sessions with anti-forgery tokens, invitations, rate-limit counters, operator TOTP
(B2; T-2.2.3 (a), (b), (c), (e); MH-01; TRD 8.1).

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

APP_ROLE = "matchdesk_app"
POLICY = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")

    # users: operator TOTP seed (sealed) and the last accepted step (single use, ASVS 6.5.1).
    op.add_column("users", sa.Column("totp_secret_enc", sa.LargeBinary(), nullable=True))
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        "operator_needs_totp", "users", "not is_operator or totp_secret_enc is not null"
    )

    # sessions: B1 fixture sessions carry no anti-forgery token; sessions are disposable, so end them.
    op.execute("delete from sessions")
    op.add_column("sessions", sa.Column("csrf_token_hash", sa.LargeBinary(), nullable=False))
    op.execute(f"grant delete on sessions to {APP_ROLE}")

    op.create_table(
        "login_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("browser_binding_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip", postgresql.INET(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_login_tokens_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_login_tokens_token_hash")),
    )
    op.execute(f"grant select, insert, update, delete on login_tokens to {APP_ROLE}")

    op.create_table(
        "auth_rate_events",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind in ('link_address', 'link_ip', 'exchange_fail_ip')", name=op.f("ck_auth_rate_events_kind")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_rate_events")),
    )
    op.create_index(
        "ix_auth_rate_events_kind_key_hash_created_at", "auth_rate_events", ["kind", "key_hash", "created_at"]
    )
    op.execute(f"grant select, insert, delete on auth_rate_events to {APP_ROLE}")

    op.create_table(
        "invitations",
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("invited_by", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role in ('controller', 'clerk', 'viewer')", name=op.f("ck_invitations_role")),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], name=op.f("fk_invitations_invited_by_users")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_invitations_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_invitations_tenant_id_id")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
    )
    op.execute("alter table invitations enable row level security")
    op.execute("alter table invitations force row level security")
    op.execute(f"create policy tenant_isolation on invitations using ({POLICY}) with check ({POLICY})")
    # Accepting needs the invitation before the tenant is known: possession of the token is the
    # authority. Read-only, and only the one row whose token hash the transaction set.
    op.execute(
        "create policy invitation_by_token on invitations for select using ("
        "token_hash = decode(nullif(current_setting('app.invitation_token_hash', true), ''), 'hex'))"
    )
    op.execute(f"grant select, insert, update on invitations to {APP_ROLE}")

    # A signed-in user reads their own memberships across tenants (sign-in, /me, tenant switch).
    op.execute(
        "create policy membership_self on memberships for select using ("
        "user_id = nullif(current_setting('app.user_id', true), '')::uuid)"
    )

    # Last-controller guard (T-2.2.3 (e), schema.md 3.1).
    op.execute(
        """
        create function memberships_last_controller_guard() returns trigger language plpgsql as $$
        begin
          if old.role = 'controller' and old.status = 'active'
             and (tg_op = 'DELETE' or new.role <> 'controller' or new.status <> 'active')
             and not exists (
               select 1 from memberships m
                where m.tenant_id = old.tenant_id and m.id <> old.id
                  and m.role = 'controller' and m.status = 'active') then
            raise exception 'cannot remove the last active controller' using errcode = 'check_violation';
          end if;
          if tg_op = 'DELETE' then
            return old;
          end if;
          return new;
        end $$;
        """
    )
    op.execute(
        "create trigger memberships_last_controller_guard before update or delete on memberships "
        "for each row execute function memberships_last_controller_guard()"
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
