"""Row-level security, application role grants, guard triggers, rule set v1 (T-2.2.1, T-2.2.4, T-4.1.3).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "matchdesk_app"

TENANT_TABLES = (
    "memberships",
    "vendors",
    "items",
    "purchase_orders",
    "po_lines",
    "qbo_bills",
    "qbo_bill_lines",
    "upload_batches",
    "documents",
    "invoices",
    "invoice_lines",
    "extraction_runs",
    "receiving_imports",
    "receipts",
    "receipt_lines",
    "item_aliases",
    "tolerance_rules",
    "match_runs",
    "line_matches",
    "exceptions",
    "exception_events",
    "audit_events",
    "idempotency_keys",
)
INSERT_ONLY = ("audit_events", "exception_events")
POLICY = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # Non-superuser application role that can never bypass row-level security (DEV-GUIDE, schema.md 4.2).
    op.execute(
        f"""
        do $$ begin
          if not exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
            create role {APP_ROLE} login nosuperuser nobypassrls nocreatedb nocreaterole;
          end if;
        end $$;
        """
    )
    op.execute(f"alter role {APP_ROLE} nosuperuser nobypassrls")
    op.execute(f"grant usage on schema public to {APP_ROLE}")

    for table in TENANT_TABLES:
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
        op.execute(f"create policy tenant_isolation on {table} using ({POLICY}) with check ({POLICY})")
        if table in INSERT_ONLY:
            op.execute(f"grant select, insert on {table} to {APP_ROLE}")
        elif table == "line_matches":
            # Results are immutable; only the supersede columns may change (schema.md 3.5).
            op.execute(f"grant select, insert on {table} to {APP_ROLE}")
            op.execute(f"grant update (is_current, superseded_by_run_id) on {table} to {APP_ROLE}")
        elif table == "tolerance_rules":
            op.execute(f"grant select, insert on {table} to {APP_ROLE}")
            op.execute(f"grant update (valid_to) on {table} to {APP_ROLE}")
        else:
            op.execute(f"grant select, insert, update, delete on {table} to {APP_ROLE}")

    # Global tables.
    op.execute(f"grant select, insert, update on tenants, users, sessions to {APP_ROLE}")
    op.execute(f"grant select on ruleset_versions to {APP_ROLE}")
    op.execute(f"grant select, insert, update, delete on job_queue to {APP_ROLE}")
    # Readiness checks that migrations are at head.
    op.execute(f"grant select on alembic_version to {APP_ROLE}")

    # A receipt_absent exception can never point at a matched result (schema.md 3.6).
    op.execute(
        """
        create function exceptions_receipt_absent_guard() returns trigger language plpgsql as $$
        begin
          if new.type = 'receipt_absent' and new.line_match_id is not null and exists (
               select 1 from line_matches lm
                where lm.id = new.line_match_id and lm.tenant_id = new.tenant_id and lm.status = 'matched') then
            raise exception 'receipt_absent exception cannot be linked to a matched line'
              using errcode = 'check_violation';
          end if;
          return new;
        end $$;
        """
    )
    op.execute(
        "create trigger exceptions_receipt_absent_guard before insert or update on exceptions "
        "for each row execute function exceptions_receipt_absent_guard()"
    )
    # Insert-only tables refuse change even from a role that was granted it by mistake.
    op.execute(
        """
        create function refuse_change() returns trigger language plpgsql as $$
        begin
          raise exception '% is insert-only', tg_table_name using errcode = 'insufficient_privilege';
        end $$;
        """
    )
    for table in INSERT_ONLY:
        op.execute(
            f"create trigger {table}_insert_only before update or delete on {table} "
            f"for each statement execute function refuse_change()"
        )

    op.execute(
        "insert into ruleset_versions (code, description, released_at) values "
        "('v1', 'Rule set v1, TRD section 8.5', now()) on conflict (code) do nothing"
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
