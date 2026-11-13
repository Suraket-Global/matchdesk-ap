"""Weekly summary S-14 (T-5.1.4; IT-25).

The figures of one week (Monday to Sunday, documents dated in it) per supplier: documents, lines
evaluated and matched, pass rate, flagged discrepancies (findings plus not received, as on S-13)
and open exceptions with their value. "Open" and "value" are those of the exception queue S-08 with
the same filters (period, supplier, status open or waiting for approval; value = the amount counted
for the line, else the variance), so the two screens always agree.

The weekly email carries totals and a link only: no supplier, price, document or line. It goes to
the account's active controllers on Monday from ``weekly_summary_hour`` (Pacific time) through the
worker, once per week (``weekly_summary_runs``), and on demand with "Send now".
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ZERO, Mailer, OutgoingMail, Settings, dec, round_cents, round_half_up
from matchdesk.exceptions.models import ExceptionRow, LineMatch
from matchdesk.identity.models import Membership, Tenant, User
from matchdesk.intake.models import InvoiceLineRow, InvoiceRow
from matchdesk.qbo.models import Vendor
from matchdesk.reporting.backtest import _current_matches, measurement_state, section_of
from matchdesk.reporting.models import WeeklySummaryRun
from matchdesk.tenancy import global_session, session

PACIFIC = ZoneInfo("America/Vancouver")
OPEN = ("open", "pending_approval")


def week_of(day: date) -> date:
    """The Monday of the week holding ``day``."""
    return day - timedelta(days=day.weekday())


def last_full_week(now: datetime) -> date:
    return week_of(now.astimezone(PACIFIC).date()) - timedelta(days=7)


def _value(e: ExceptionRow) -> Decimal:
    v = e.reported_amount if e.reported_amount is not None else e.variance_amount
    return dec(v) if v is not None else ZERO


def summary(s: Session, week_start: date) -> dict[str, Any]:
    """Figures of the week, per supplier and in total (tenant session)."""
    week_start = week_of(week_start)
    week_end = week_start + timedelta(days=6)
    invoices = list(
        s.scalars(
            select(InvoiceRow).where(InvoiceRow.doc_date >= week_start, InvoiceRow.doc_date <= week_end)
        ).all()
    )
    names = {v.id: v.name for v in s.scalars(select(Vendor))}
    by_vendor: dict[Any, dict[str, Any]] = defaultdict(
        lambda: {
            "documents": 0,
            "lines": 0,
            "lines_matched": 0,
            "open_count": 0,
            "open_value": ZERO,
            "flagged": ZERO,
        }
    )
    vendor_of = {i.id: i.vendor_id for i in invoices}
    for i in invoices:
        by_vendor[i.vendor_id]["documents"] += 1
    ids = [i.id for i in invoices]
    if ids:
        for inv_id, status in s.execute(
            select(InvoiceLineRow.invoice_id, LineMatch.status)
            .join(LineMatch, LineMatch.invoice_line_id == InvoiceLineRow.id)
            .where(InvoiceLineRow.invoice_id.in_(ids), LineMatch.is_current.is_(True))
        ).all():
            row = by_vendor[vendor_of[inv_id]]
            row["lines"] += 1
            row["lines_matched"] += 1 if status == "matched" else 0
        for e in s.scalars(select(ExceptionRow).where(ExceptionRow.invoice_id.in_(ids))):
            row = by_vendor[vendor_of[e.invoice_id]]
            if e.status in OPEN:
                row["open_count"] += 1
                row["open_value"] += _value(e)
            if section_of(e) in ("finding", "not_received"):
                row["flagged"] += dec(e.reported_amount) if e.reported_amount is not None else ZERO

    def out(vendor_id: Any, r: dict[str, Any]) -> dict[str, Any]:
        return {
            "vendor_id": str(vendor_id) if vendor_id else None,
            "vendor_name": names.get(vendor_id) if vendor_id else None,
            "documents": r["documents"],
            "lines": r["lines"],
            "lines_matched": r["lines_matched"],
            "pass_rate_pct": str(
                round_half_up(Decimal(r["lines_matched"]) * 100 / r["lines"], Decimal("0.1"))
            )
            if r["lines"]
            else None,
            "open_count": r["open_count"],
            "open_value": str(round_cents(r["open_value"])),
            "flagged_amount": str(round_cents(r["flagged"])),
        }

    rows = sorted(
        (out(v, r) for v, r in by_vendor.items()),
        key=lambda x: (-dec(x["open_value"]), x["vendor_name"] or "~"),
    )
    total = {
        "documents": sum(r["documents"] for r in by_vendor.values()),
        "lines": sum(r["lines"] for r in by_vendor.values()),
        "lines_matched": sum(r["lines_matched"] for r in by_vendor.values()),
        "open_count": sum(r["open_count"] for r in by_vendor.values()),
        "open_value": str(round_cents(sum((r["open_value"] for r in by_vendor.values()), ZERO))),
        "flagged_amount": str(round_cents(sum((r["flagged"] for r in by_vendor.values()), ZERO))),
    }
    total["pass_rate_pct"] = (
        str(round_half_up(Decimal(total["lines_matched"]) * 100 / total["lines"], Decimal("0.1")))
        if total["lines"]
        else None
    )
    matches = _current_matches(s, ids) if ids else []
    item_lines = sum(1 for lm, _ln in matches if lm.line_kind == "item")
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        # B8: whether the week's figures were measured, so an empty week never reads as a clean one.
        "state": measurement_state(s, invoices, matches, item_lines),
        "suppliers": rows,
        "total": total,
    }


def email_text(tenant_name: str, fig: dict[str, Any], link: str) -> tuple[str, str]:
    """Totals and a link only (IT-25): no supplier, price, document or line."""
    t = fig["total"]
    start = date.fromisoformat(fig["week_start"])
    end = date.fromisoformat(fig["week_end"])
    span = f"{start.day} {start:%b} to {end.day} {end:%b %Y}"
    subject = f"MatchDesk weekly summary, {span}"
    rate = f"{t['pass_rate_pct']}%" if t["pass_rate_pct"] is not None else "not measured"
    body = "\n".join(
        [
            f"Weekly summary for {tenant_name}, documents dated {span}.",
            "",
            f"Documents: {t['documents']}",
            f"Lines checked: {t['lines']} (passed every check: {rate})",
            f"Flagged discrepancies: CAD {t['flagged_amount']}",
            f"Open exceptions: {t['open_count']}, CAD {t['open_value']}",
            "",
            f"See the details by supplier: {link}",
            "",
            "You receive this because you are a controller of this MatchDesk account.",
        ]
    )
    return subject, body


def recipients(s: Session) -> list[str]:
    return list(
        s.scalars(
            select(User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.role == "controller",
                Membership.status == "active",
                User.deactivated_at.is_(None),
            )
            .order_by(User.email)
        ).all()
    )


def send_weekly(
    engine: Any,
    tenant_id: uuid.UUID,
    week_start: date,
    trigger: str,
    mailer: Mailer,
    settings: Settings,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """Send the week's email once per trigger and week. Returns the run, or None when already sent."""
    week_start = week_of(week_start)
    with global_session(engine) as g:
        tenant = g.get(Tenant, tenant_id)
        name = tenant.name if tenant else "your account"
    with session(tenant_id, engine) as s:
        fig = summary(s, week_start)
        to = recipients(s)
        inserted = s.execute(
            pg_insert(WeeklySummaryRun)
            .values(
                tenant_id=tenant_id,
                week_start=week_start,
                trigger=trigger,
                recipients=len(to),
                sent_by=user_id,
                figures=fig["total"],
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "week_start", "trigger"])
            .returning(WeeklySummaryRun.id)
        ).scalar()
        if inserted is None:
            return None
        write_audit(
            s,
            tenant_id,
            actor_type="user" if user_id else "job",
            actor_user_id=user_id,
            action="weekly_summary.sent",
            entity_type="weekly_summary",
            entity_id=inserted,
            after={"week_start": fig["week_start"], "recipients": len(to), "trigger": trigger},
        )
    link = f"{settings.app_base_url}/reports/weekly?week={fig['week_start']}"
    subject, body = email_text(name, fig, link)
    for addr in to:
        mailer.send(OutgoingMail(to=addr, subject=subject, body=body))
    return {"id": str(inserted), "week_start": fig["week_start"], "recipients": len(to), "trigger": trigger}


def due_weekly(engine: Any, now: datetime, mailer: Mailer, settings: Settings) -> int:
    """The scheduled job: on Monday from ``weekly_summary_hour`` Pacific, last week's email for every
    account that has not had it. Safe to call every minute; returns the number sent."""
    local = now.astimezone(PACIFIC)
    if local.weekday() != 0 or local.hour < settings.weekly_summary_hour:
        return 0
    week = last_full_week(now)
    with global_session(engine) as g:
        tenants = list(g.scalars(select(Tenant.id).where(Tenant.status != "ended")).all())
    sent = 0
    for tid in tenants:
        with session(tid, engine) as s:
            done = s.scalar(
                select(func.count())
                .select_from(WeeklySummaryRun)
                .where(WeeklySummaryRun.week_start == week, WeeklySummaryRun.trigger == "scheduled")
            )
        if not done and send_weekly(engine, tid, week, "scheduled", mailer, settings):
            sent += 1
    return sent


def last_sent(s: Session) -> list[dict[str, Any]]:
    rows = s.scalars(select(WeeklySummaryRun).order_by(WeeklySummaryRun.created_at.desc()).limit(10)).all()
    return [
        {
            "week_start": r.week_start.isoformat(),
            "trigger": r.trigger,
            "recipients": r.recipients,
            "sent_at": r.created_at.isoformat() if r.created_at else datetime.now(UTC).isoformat(),
        }
        for r in rows
    ]
