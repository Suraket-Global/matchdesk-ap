"""Trial reminder emails (owner, 2026-11-19): during the 7-day free trial ("sample" in code) the
account's controllers get three short emails that name the one next step, on day 1, day 3 and day
6. Each goes once per account (``tenants.trial_nudges``); a step already done is not nagged about.

Only facts and counts are used (``tenancy.trial_progress``); no document content goes into an email.
Safe to run every minute: it sends only what is due and records what it sent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from matchdesk.audit import write_audit
from matchdesk.core import Mailer, OutgoingMail, Settings, get_logger
from matchdesk.identity.models import Membership, Tenant, User
from matchdesk.tenancy import SAMPLE_DAYS, global_session, sample_state, session

log = get_logger("matchdesk.reporting.trial")

# (kind, hours after the trial starts)
NUDGES: tuple[tuple[str, int], ...] = (("day1", 20), ("day3", 68), ("day6", 140))

_STEP_WORDS = {
    "connect_qbo": (
        "Connect QuickBooks Online",
        "It takes a minute: Intuit's own sign-in, read-only. MatchDesk reads purchase orders, bills, "
        "vendors and items and never changes anything.",
        "/settings/quickbooks",
    ),
    "load_receiving": (
        "Load your receiving record",
        "Export what your warehouse recorded as received (a CSV or Excel file: PO number, quantity, "
        "date). A sample file is on the Receiving page.",
        "/receiving",
    ),
    "upload_invoices": (
        "Upload last month's supplier invoices",
        "Drop up to 100 invoice PDFs, scans or photos on the Intake page.",
        "/intake",
    ),
    "review_documents": (
        "Confirm the documents waiting for you",
        "Some invoices were read from a scan or could not be read with certainty. Check the prefilled "
        "fields against the image and confirm.",
        "/invoices",
    ),
    "read_findings": (
        "Look at your findings",
        "The exception list shows only the lines that disagree with the purchase order or what arrived, "
        "each with its dollar amount.",
        "/exceptions",
    ),
}


def _money(amount: str, currency: str) -> str:
    return f"{currency} {Decimal(amount):,.2f}"


def nudge_mail(
    kind: str, account: str, currency: str, st: dict[str, Any], settings: Settings
) -> tuple[str, str]:
    """Subject and plain-text body of one reminder."""
    p = st["progress"]
    title, how, path = _STEP_WORDS[p["next_step"]]
    left = max(0, SAMPLE_DAYS - (st.get("day") or 1))
    base = settings.app_base_url
    lines = [f"Your MatchDesk free trial for {account}: day {st.get('day')} of {SAMPLE_DAYS}.", ""]
    if kind == "day6":
        subject = f"Your MatchDesk free trial ends tomorrow ({account})"
        if p["findings"]:
            lines += [
                f"So far MatchDesk has flagged {p['findings']} line(s) totalling "
                f"{_money(p['findings_amount'], currency)}.",
                "",
                "To check the whole month and get the approved report, reply to this email to start the "
                "30-day pilot (refunded if it finds less than the fee).",
                "",
            ]
        else:
            lines += ["Here is what is left to see your first results:", ""]
    else:
        subject = f"Next step in your MatchDesk trial: {title.lower()}"
    lines += [
        f"Next step: {title}.",
        how,
        f"{base}{path}",
        "",
        f"Your checklist: {base}/onboarding",
        "",
        "Stuck? Reply to this email and we will set it up with you on a 15-minute call.",
        "",
        f"{st['invoices_used']} of {st['invoice_limit']} invoices used; {left} day(s) left.",
        "",
        "MatchDesk",
    ]
    return subject, "\n".join(lines)


def due_trial_nudges(engine: Any, now: datetime, mailer: Mailer, settings: Settings) -> int:
    """Send every reminder that is due; returns how many emails were sent."""
    sent = 0
    with global_session(engine) as g:
        trials = [
            (t.id, t.name, t.currency, list(t.trial_nudges or []), t.sample_ends_at)
            for t in g.scalars(select(Tenant).where(Tenant.status == "sample"))
            if t.sample_ends_at is not None and now < t.sample_ends_at
        ]
    for tid, name, currency, done, ends in trials:
        started = ends - timedelta(days=SAMPLE_DAYS)
        due = [k for k, hours in NUDGES if k not in done and now >= started + timedelta(hours=hours)]
        if not due:
            continue
        kind = due[-1]  # a late run sends only the latest due reminder, never a burst
        with session(tid, engine) as s:
            st = sample_state(s, tid, now)
            to = [
                email
                for (email,) in s.execute(
                    select(User.email)
                    .join(Membership, Membership.user_id == User.id)
                    .where(
                        Membership.tenant_id == tid,
                        Membership.role == "controller",
                        Membership.status == "active",
                        User.deactivated_at.is_(None),
                    )
                ).all()
            ]
        if st is None:
            continue
        subject, body = nudge_mail(kind, name, currency, st, settings)
        for address in to:
            try:
                mailer.send(OutgoingMail(to=address, subject=subject, body=body))
                sent += 1
            except Exception as exc:  # the address and body are never logged
                log.error("trial_nudge_failed", extra={"reason": type(exc).__name__})
        with global_session(engine) as g:
            t = g.get(Tenant, tid)
            if t is not None:
                t.trial_nudges = sorted({*(t.trial_nudges or []), *due})
        with session(tid, engine) as s:
            write_audit(
                s,
                tid,
                actor_type="job",
                action="trial.reminder_sent",
                entity_type="tenant",
                entity_id=tid,
                after={"kind": kind, "recipients": len(to), "next_step": st["progress"]["next_step"]},
            )
    return sent


__all__ = ["NUDGES", "due_trial_nudges", "nudge_mail"]
