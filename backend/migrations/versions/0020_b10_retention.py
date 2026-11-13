"""B10 (2026-11-13): archive completeness and deletion coordination (outside QA items 1 and 2).

- ``archive_exports``: ``expected_count``, ``included_count``, ``missing_count`` and
  ``missing_document_ids``; status ``incomplete`` when an original could not be read. A ready archive
  has nothing missing; an incomplete one has at least one missing original and still has its file.
- ``deletion_requests``: status ``deleting`` (claimed by the worker before the first file is removed;
  cancellation is refused from then on), ``claimed_at``; the latest verified archive state when the
  request was made or an archive finished while it was open (``archive_state``, ``archive_included``,
  ``archive_expected``, ``archive_checked_at``) so the operator sees it without reading tenant data;
  and ``archive_acknowledged``, the controller's explicit acknowledgement that no complete archive
  exists. Constraints on the existing tables are added ``NOT VALID`` and validated.
- ``purge_tenant()`` deletes only an account whose deletion the worker has claimed (``deleting``).

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def _check(table: str, name: str, expr: str) -> None:
    op.execute(f"alter table {table} add constraint {name} check ({expr}) not valid")
    op.execute(f"alter table {table} validate constraint {name}")


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.add_column("archive_exports", sa.Column("expected_count", sa.Integer(), nullable=True))
    op.add_column("archive_exports", sa.Column("included_count", sa.Integer(), nullable=True))
    op.add_column("archive_exports", sa.Column("missing_count", sa.Integer(), nullable=True))
    op.add_column(
        "archive_exports",
        sa.Column("missing_document_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute("alter table archive_exports drop constraint ck_archive_exports_status")
    _check(
        "archive_exports",
        "ck_archive_exports_status",
        "status in ('queued', 'running', 'ready', 'incomplete', 'failed', 'expired')",
    )
    _check(
        "archive_exports",
        "ck_archive_exports_ready_complete",
        "status <> 'ready' or coalesce(missing_count, 0) = 0",
    )
    _check(
        "archive_exports",
        "ck_archive_exports_incomplete_has_file",
        "status <> 'incomplete' or (document_id is not null and expires_at is not null and missing_count > 0)",
    )

    op.add_column("deletion_requests", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deletion_requests", sa.Column("archive_state", sa.Text(), nullable=True))
    op.add_column("deletion_requests", sa.Column("archive_included", sa.Integer(), nullable=True))
    op.add_column("deletion_requests", sa.Column("archive_expected", sa.Integer(), nullable=True))
    op.add_column(
        "deletion_requests", sa.Column("archive_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "deletion_requests",
        sa.Column("archive_acknowledged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.execute("alter table deletion_requests drop constraint ck_deletion_requests_status")
    _check(
        "deletion_requests",
        "ck_deletion_requests_status",
        "status in ('requested', 'scheduled', 'deleting', 'declined', 'cancelled', 'executed')",
    )
    _check(
        "deletion_requests",
        "ck_deletion_requests_deleting_claimed",
        "status <> 'deleting' or (claimed_at is not null and delete_after is not null)",
    )
    _check(
        "deletion_requests",
        "ck_deletion_requests_archive_state",
        "archive_state is null or archive_state in ('none', 'complete', 'incomplete', 'failed', 'expired')",
    )
    op.execute(
        """
        create or replace function purge_tenant(t uuid) returns integer language plpgsql
        security definer set search_path = public as $$
        declare
          remaining text[];
          tbl text;
          progressed boolean;
          n integer;
          total integer := 0;
          req record;
        begin
          perform set_config('app.tenant_id', t::text, true);
          perform set_config('app.purge', 'on', true);
          select id, requested_by into req from deletion_requests
           where tenant_id = t and status = 'deleting' and delete_after <= now();
          if req.id is null then
            raise exception 'no claimed deletion is due for this account' using errcode = 'insufficient_privilege';
          end if;
          delete from sessions where active_tenant_id = t;
          delete from job_queue where payload->>'tenant_id' = t::text;
          select array_agg(c.table_name::text order by c.table_name) into remaining
            from information_schema.columns c
            join information_schema.tables tb
              on tb.table_schema = c.table_schema and tb.table_name = c.table_name
           where c.table_schema = 'public' and c.column_name = 'tenant_id'
             and tb.table_type = 'BASE TABLE'
             and c.table_name <> 'deletion_ledger';
          loop
            progressed := false;
            foreach tbl in array remaining loop
              begin
                execute format('delete from %I where tenant_id = $1', tbl) using t;
                get diagnostics n = row_count;
                total := total + n;
                remaining := array_remove(remaining, tbl);
                progressed := true;
              exception when foreign_key_violation then
                null;  -- a row still refers to this table; try again after the others
              end;
            end loop;
            exit when coalesce(cardinality(remaining), 0) = 0;
            if not progressed then
              raise exception 'account deletion is blocked by %', remaining;
            end if;
          end loop;
          delete from tenants where id = t;
          insert into deletion_ledger (tenant_id, scope, entity_id, requested_by, executed_at, rows_deleted)
          values (t, 'tenant', t, req.requested_by, now(), total);
          return total;
        end $$;
        """
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
