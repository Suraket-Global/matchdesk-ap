"""B3/B4 review fixes (2026-11-12), finding M5: an approved back-test report is immutable as a whole.

- ``backtest_reports_approved_immutable`` now compares the whole row except ``status``; the only
  change allowed to an approved version is becoming ``superseded``, and a superseded version that
  was approved never changes again. Migration 0013 compared only some columns.
- ``report_findings_only_while_generating``: a finding row may be inserted only while its report is
  ``generating`` (the draft being built); nothing is added to a draft, approved or superseded report.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute(
        """
        create or replace function backtest_reports_approved_immutable() returns trigger
        language plpgsql as $$
        begin
          if old.approved_at is not null and old.status in ('approved', 'superseded') then
            if (to_jsonb(new) - 'status') is distinct from (to_jsonb(old) - 'status')
               or not (new.status = old.status or (old.status = 'approved' and new.status = 'superseded'))
            then
              raise exception 'an approved report version is immutable' using errcode = 'check_violation';
            end if;
          end if;
          return new;
        end $$;
        """
    )
    op.execute(
        """
        create function report_findings_only_while_generating() returns trigger
        language plpgsql as $$
        declare
          report_status text;
        begin
          select status into report_status from backtest_reports
           where id = new.report_id and tenant_id = new.tenant_id;
          if report_status is distinct from 'generating' then
            raise exception 'findings are added only while a report is generating'
              using errcode = 'check_violation';
          end if;
          return new;
        end $$;
        """
    )
    op.execute(
        "create trigger report_findings_only_while_generating before insert on report_findings "
        "for each row execute function report_findings_only_while_generating()"
    )


def downgrade() -> None:
    raise NotImplementedError("No down-migrations (schema.md section 9)")
