"""Back-test report: frozen snapshot, coverage by evidence class, approval, export, refund criterion
(T-5.1.1, T-5.1.2; T-5.1.3 (c) refund evaluation; MH-12, MH-07, MH-16; B3).

A draft freezes, at its data cut-off, every exception on the invoices and credit notes dated in the
period into ``report_findings`` with its section and amount (``reported_amount``, the per-line rule
of TRD 8.5). "Not received" is listed apart from findings, unverified amounts are shown and never
dropped, and waived exceptions are listed and still counted in the qualifying total. Approval is
refused while any result is stale, any approval or document review is pending, or the draft is not
the latest; an approved version is immutable and a later approval supersedes it. The refund result
is computed only from the governing report's stored qualifying total.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ZERO, ConflictError, dec, round_cents, text_pdf
from matchdesk.exceptions import stale_runs
from matchdesk.exceptions.models import Approval, ExceptionRow, LineMatch
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow
from matchdesk.qbo.models import PoLineRow, PurchaseOrderRow, QboBillRow, Vendor
from matchdesk.receiving import counting_receipt_totals
from matchdesk.receiving.models import ReceiptLineRow, ReceivingImportRow
from matchdesk.reporting.models import BacktestReport, ReportFinding
from matchdesk.reporting.refund import DEFAULT_THRESHOLD, RefundCalculation
from matchdesk.tenancy import advisory_lock

REMOVED_BY_EVIDENCE = frozenset({"resolved_by_credit", "source_corrected", "not_a_duplicate"})
UNFINISHED_DOCUMENT_STATES = ("queued", "running", "retry_wait", "needs_review")
DRAFT_MARK = "DRAFT - NOT APPROVED"


def section_of(e: ExceptionRow) -> str | None:
    """Report section of one exception, or None when evidence removed it (credit, corrected source,
    not a duplicate, no longer raised)."""
    if e.status == "auto_closed":
        return None
    if e.status == "resolved" and e.resolution_code in REMOVED_BY_EVIDENCE:
        return None
    if e.status == "waived":
        return "waived"
    if e.status == "pending_approval" or e.value_class == "open_undecided":
        return "open"
    if e.value_class == "finding_candidate":
        if e.sub_reason == "not_received" or e.resolution_code == "confirmed_not_received":
            return "not_received"
        return "finding"
    if e.value_class == "unverified":
        return "unverified"
    return None


def _pct(part: int, whole: int) -> Decimal | None:
    if whole == 0:
        return None
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.01"))


def _paid_map(s: Session, invoices: list[InvoiceRow]) -> dict[uuid.UUID, str]:
    bills: dict[tuple[uuid.UUID | None, str | None], str] = {
        (b.vendor_id, b.doc_number_norm): b.paid_status
        for b in s.scalars(select(QboBillRow).where(QboBillRow.txn_type == "bill"))
    }
    return {i.id: bills.get((i.vendor_id, i.doc_number_norm), "unknown") for i in invoices}


def _period_invoices(s: Session, start: date, end: date) -> list[InvoiceRow]:
    return list(
        s.scalars(
            select(InvoiceRow)
            .where(InvoiceRow.doc_date >= start, InvoiceRow.doc_date <= end)
            .order_by(InvoiceRow.doc_date, InvoiceRow.doc_number_norm, InvoiceRow.id)
        ).all()
    )


def _current_matches(s: Session, invoice_ids: list[uuid.UUID]) -> list[tuple[LineMatch, InvoiceLineRow]]:
    return list(
        s.execute(
            select(LineMatch, InvoiceLineRow)
            .join(InvoiceLineRow, InvoiceLineRow.id == LineMatch.invoice_line_id)
            .where(InvoiceLineRow.invoice_id.in_(invoice_ids), LineMatch.is_current.is_(True))
        ).all()
    )


def blocking_reasons(s: Session, start: date, end: date) -> list[str]:
    invoices = _period_invoices(s, start, end)
    ids = [i.id for i in invoices]
    reasons: list[str] = []
    states = Counter(
        s.scalars(
            select(DocumentRow.state).where(DocumentRow.id.in_({i.document_id for i in invoices}))
        ).all()
    )
    unfinished = sum(states.get(st, 0) for st in UNFINISHED_DOCUMENT_STATES)
    if unfinished:
        reasons.append(f"{unfinished} document(s) still processing or waiting for review")
    pending = s.scalar(select(func.count()).select_from(Approval).where(Approval.status == "pending"))
    if pending:
        reasons.append(f"{pending} approval(s) pending")
    matches = _current_matches(s, ids)
    lines = s.scalar(
        select(func.count()).select_from(InvoiceLineRow).where(InvoiceLineRow.invoice_id.in_(ids))
    )
    if (lines or 0) > len(matches):
        reasons.append(f"{int(lines or 0) - len(matches)} line(s) not matched yet")
    stale = stale_runs(s, list({lm.match_run_id for lm, _ln in matches}))
    if any(stale.values()):
        reasons.append("results are out of date: inputs changed since the last match run")
    return reasons


def _period_lock_key(tenant_id: uuid.UUID, start: date, end: date) -> str:
    return f"backtest:{tenant_id}:{start.isoformat()}:{end.isoformat()}"


def create_draft(
    s: Session, tenant_id: uuid.UUID, user_id: uuid.UUID | None, start: date, end: date
) -> BacktestReport:
    """Create (or refresh, as a new version) a draft with a frozen snapshot (T-5.1.1 (a) to (e))."""
    if end < start:
        raise ValueError("the period ends before it starts")
    advisory_lock(s, _period_lock_key(tenant_id, start, end))  # one draft or approval at a time (m5)
    now = datetime.now(UTC)
    prior = s.scalars(
        select(BacktestReport).where(BacktestReport.period_start == start, BacktestReport.period_end == end)
    ).all()
    for r in prior:
        if r.status == "draft":
            r.status = "superseded"
    s.flush()
    invoices = _period_invoices(s, start, end)
    ids = [i.id for i in invoices]
    by_id = {i.id: i for i in invoices}
    excs = list(s.scalars(select(ExceptionRow).where(ExceptionRow.invoice_id.in_(ids))).all())
    matches = _current_matches(s, ids)
    stale = stale_runs(s, list({lm.match_run_id for lm, _ln in matches}))
    paid = _paid_map(s, invoices)
    lines = {ln.id: ln for ln in s.scalars(select(InvoiceLineRow).where(InvoiceLineRow.invoice_id.in_(ids)))}
    lm_by_line = {lm.invoice_line_id: lm for lm, _ln in matches}
    pos = {p.id: p for p in s.scalars(select(PurchaseOrderRow))}
    po_lines = {pl.id: pl for pl in s.scalars(select(PoLineRow))}
    vendors = {v.id: v.name for v in s.scalars(select(Vendor))}

    report = BacktestReport(
        tenant_id=tenant_id,
        period_start=start,
        period_end=end,
        version_no=max((r.version_no for r in prior), default=0) + 1,
        status="generating",
        data_cutoff_at=now,
        totals={},
        created_by=user_id,
        supersedes_report_id=max(prior, key=lambda r: r.version_no).id if prior else None,
    )
    s.add(report)
    s.flush()
    sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
    counts: Counter[str] = Counter()
    paid_split: dict[str, Decimal] = defaultdict(lambda: ZERO)
    qualifying = ZERO
    for e in excs:
        section = section_of(e)
        if section is None:
            continue
        amount = dec(e.reported_amount) if e.reported_amount is not None else ZERO
        inv = by_id[e.invoice_id]
        ln = lines.get(e.invoice_line_id) if e.invoice_line_id else None
        lm = lm_by_line.get(e.invoice_line_id) if e.invoice_line_id else None
        pl = po_lines.get(lm.po_line_id) if lm and lm.po_line_id else None
        po = (
            pos.get(pl.purchase_order_id)
            if pl
            else (pos.get(inv.purchase_order_id) if inv.purchase_order_id else None)
        )
        sums[section] += amount
        counts[section] += 1
        if e.qualifying:
            qualifying += amount  # a waiver never lowers it (Decision.md 5.1)
        if section in ("finding", "not_received"):
            paid_split[paid[inv.id]] += amount
        s.add(
            ReportFinding(
                tenant_id=tenant_id,
                report_id=report.id,
                exception_id=e.id,
                section=section,
                type=e.type,
                vendor_id=inv.vendor_id,
                amount=round_cents(amount),
                qualifying=e.qualifying,
                paid_status=paid[inv.id],
                snapshot={
                    "doc_type": inv.doc_type,
                    "doc_number": inv.doc_number,
                    "doc_date": inv.doc_date.isoformat() if inv.doc_date else None,
                    "vendor_name": vendors.get(inv.vendor_id) if inv.vendor_id else inv.vendor_name_read,
                    "po_number": po.po_number if po else inv.po_number_read,
                    "line_no": ln.line_no if ln else None,
                    "supplier_item_code": ln.supplier_item_code if ln else None,
                    "qty_invoiced": str(ln.qty) if ln and ln.qty is not None else None,
                    "unit_price": str(ln.unit_price) if ln and ln.unit_price is not None else None,
                    "qty_ordered": str(lm.qty_ordered) if lm and lm.qty_ordered is not None else None,
                    "qty_received_cum": str(lm.qty_received_cum)
                    if lm and lm.qty_received_cum is not None
                    else None,
                    "po_unit_price": str(lm.po_unit_price) if lm and lm.po_unit_price is not None else None,
                    "sub_reason": e.sub_reason,
                    "status": e.status,
                    "resolution_code": e.resolution_code,
                    "variance_amount": str(e.variance_amount) if e.variance_amount is not None else None,
                    "label": e.label,
                },
            )
        )
    item = [(lm, ln) for lm, ln in matches if lm.line_kind == "item"]
    cov = _coverage(s, item)
    history = s.scalar(
        select(func.min(InvoiceRow.doc_date)).where(
            InvoiceRow.purchase_order_id.in_({i.purchase_order_id for i in invoices if i.purchase_order_id})
        )
    )
    report.totals = {
        "documents": len(invoices),
        "lines_evaluated": len(matches),
        "item_lines": len(item),
        "lines_matched": sum(1 for lm, _ln in matches if lm.status == "matched"),
        "sections": {
            k: {"count": counts[k], "amount": str(round_cents(sums[k]))}
            for k in ("finding", "not_received", "unverified", "waived", "open")
        },
        "paid_split": {k: str(round_cents(v)) for k, v in sorted(paid_split.items())},
        "qualifying_amount": str(round_cents(qualifying)),
        "stale_lines": sum(1 for lm, _ln in matches if stale.get(lm.match_run_id)),
    }
    report.history_read_from = history
    report.receipt_coverage_pct = cov["receipt_coverage_pct"]
    report.coverage_class_a_pct = cov["coverage_class_a_pct"]
    report.coverage_class_b_pct = cov["coverage_class_b_pct"]
    report.class_c_only_lines = sum(
        1
        for e in excs
        if e.type == "receipt_absent" and e.sub_reason == "supplier_slip_only" and section_of(e) is not None
    )
    report.not_received_amount = round_cents(sums["not_received"])
    report.unverified_amount = round_cents(sums["unverified"])
    report.findings_amount = round_cents(sums["finding"])
    report.qualifying_amount = round_cents(qualifying)
    report.is_stale = any(stale.values())
    s.flush()  # every finding row is inserted while the report is still ``generating`` (M5)
    report.status = "draft"
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
        action="report.drafted",
        entity_type="backtest_report",
        entity_id=report.id,
        after={"version": report.version_no, "qualifying": str(report.qualifying_amount)},
    )
    return report


def _coverage(s: Session, item: list[tuple[LineMatch, InvoiceLineRow]]) -> dict[str, Decimal | None]:
    """Receipt coverage over invoiced PO item lines, one denominator for all three figures:
    lines with a counting receipt, lines inside a declared-complete warehouse log (class A), and
    lines with a counting receipt from a signed delivery document (class B)."""
    covered = sum(1 for lm, _ln in item if lm.covered)
    with_receipt = sum(1 for lm, _ln in item if lm.receipt_line_count > 0)
    class_b_lines = _class_b_lines(s, [lm.po_line_id for lm, _ln in item if lm.po_line_id])
    class_b = sum(1 for lm, _ln in item if lm.po_line_id in class_b_lines and lm.receipt_line_count > 0)
    return {
        "receipt_coverage_pct": _pct(with_receipt, len(item)),
        "coverage_class_a_pct": _pct(covered, len(item)),
        "coverage_class_b_pct": _pct(class_b, len(item)),
    }


def live_coverage(s: Session, start: date, end: date) -> dict[str, Any]:
    """The coverage figures of a draft, computed from the current results now (S-08 strip; B3/B4
    review W3: the strip no longer waits for a report draft)."""
    ids = [i.id for i in _period_invoices(s, start, end)]
    item = [(lm, ln) for lm, ln in _current_matches(s, ids) if lm.line_kind == "item"]
    cov = _coverage(s, item)
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "item_lines": len(item),
        **{k: (str(v) if v is not None else None) for k, v in cov.items()},
    }


def _class_b_lines(s: Session, po_line_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """PO lines with at least one counting receipt line from a class B import."""
    counting = counting_receipt_totals(s, po_line_ids)
    rows = s.execute(
        select(ReceiptLineRow.po_line_id)
        .join(ReceivingImportRow, ReceivingImportRow.id == ReceiptLineRow.receiving_import_id)
        .where(ReceiptLineRow.po_line_id.in_(po_line_ids), ReceivingImportRow.evidence_class == "B")
    ).all()
    return {r[0] for r in rows if r[0] in counting}


def snapshot_changed(s: Session, report: BacktestReport) -> bool:
    """True when the draft no longer matches what a rebuild would freeze now: a document entered or
    left the period, or an exception in scope changed section, amount or qualifying after
    ``data_cutoff_at`` (B3/B4 review M4). Compares the frozen rows with the current ones, no clock."""
    invoices = _period_invoices(s, report.period_start, report.period_end)
    if len(invoices) != int(report.totals.get("documents", -1)):
        return True
    ids = [i.id for i in invoices]
    current: set[tuple[uuid.UUID, str, Decimal, bool]] = set()
    for e in s.scalars(select(ExceptionRow).where(ExceptionRow.invoice_id.in_(ids))):
        section = section_of(e)
        if section is None:
            continue
        amount = round_cents(dec(e.reported_amount) if e.reported_amount is not None else ZERO)
        current.add((e.id, section, amount, bool(e.qualifying)))
    frozen = {
        (f.exception_id, f.section, round_cents(dec(f.amount)), bool(f.qualifying))
        for f in findings_of(s, report.id)
    }
    return current != frozen


def approve(s: Session, report: BacktestReport, user_id: uuid.UUID) -> BacktestReport:
    """Idempotent. Refused while any blocking check fails; supersedes an earlier approved version."""
    if report.status == "approved":
        return report
    advisory_lock(s, _period_lock_key(report.tenant_id, report.period_start, report.period_end))
    s.refresh(report)  # a draft refreshed meanwhile is superseded and is no longer approvable
    if report.status != "draft":
        raise ConflictError(f"a report in status {report.status} cannot be approved")
    reasons = blocking_reasons(s, report.period_start, report.period_end)
    if report.is_stale:
        reasons.append("this draft was built from out-of-date results; refresh it")
    elif snapshot_changed(s, report):
        reasons.append("results changed after this draft's data cut-off; refresh the draft")
    if reasons:
        raise ConflictError("; ".join(reasons))
    earlier = s.scalar(
        select(BacktestReport).where(
            BacktestReport.period_start == report.period_start,
            BacktestReport.period_end == report.period_end,
            BacktestReport.status == "approved",
        )
    )
    if earlier is not None:
        earlier.status = "superseded"
        s.flush()
    report.status, report.approved_by, report.approved_at = "approved", user_id, datetime.now(UTC)
    s.flush()
    write_audit(
        s,
        report.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="report.approved",
        entity_type="backtest_report",
        entity_id=report.id,
        after={"version": report.version_no, "supersedes": str(earlier.id) if earlier else None},
    )
    return report


def refund_evaluation(report: BacktestReport, threshold: Decimal = DEFAULT_THRESHOLD) -> RefundCalculation:
    """From the stored qualifying total of the approved (governing) report only (IT-17). A superseded
    version is refused (B3/B4 review M6); the threshold is the server's, never the caller's."""
    if report.status != "approved" or report.approved_at is None:
        raise ConflictError("the refund criterion is evaluated on the approved report version only")
    qualifying = dec(report.qualifying_amount or 0)
    return RefundCalculation(
        qualifying, dec(report.unverified_amount or 0), refund_due=qualifying < dec(threshold)
    )


def findings_of(s: Session, report_id: uuid.UUID) -> list[ReportFinding]:
    return list(
        s.scalars(
            select(ReportFinding)
            .where(ReportFinding.report_id == report_id)
            .order_by(ReportFinding.section, ReportFinding.created_at, ReportFinding.id)
        ).all()
    )


def describe_report(r: BacktestReport) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "period_start": r.period_start.isoformat(),
        "period_end": r.period_end.isoformat(),
        "version_no": r.version_no,
        "status": r.status,
        "data_cutoff_at": r.data_cutoff_at.isoformat(),
        "totals": r.totals,
        "history_read_from": r.history_read_from.isoformat() if r.history_read_from else None,
        "receipt_coverage_pct": str(r.receipt_coverage_pct) if r.receipt_coverage_pct is not None else None,
        "coverage_class_a_pct": str(r.coverage_class_a_pct) if r.coverage_class_a_pct is not None else None,
        "coverage_class_b_pct": str(r.coverage_class_b_pct) if r.coverage_class_b_pct is not None else None,
        "class_c_only_lines": r.class_c_only_lines,
        "findings_amount": str(r.findings_amount),
        "not_received_amount": str(r.not_received_amount),
        "unverified_amount": str(r.unverified_amount),
        "qualifying_amount": str(r.qualifying_amount),
        "is_stale": r.is_stale,
        "approved_by": str(r.approved_by) if r.approved_by else None,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "draft_mark": None
        if r.status == "approved"
        else DRAFT_MARK
        if r.status == "draft"
        else r.status.upper(),
    }


def _cell(value: Any) -> str:
    """CSV formula-injection guard (UT-11): a cell starting with = + - @ or a control is prefixed.
    Numbers (amounts, line numbers, booleans) are written as numbers, so a credit of -12.50 stays a
    number in a spreadsheet (B3/B4 review m3)."""
    if isinstance(value, (Decimal, int)):
        return str(value)
    text = "" if value is None else str(value)
    if text and (text[0] in "=+-@\t\r" or text[0] == "＝"):
        return "'" + text
    return text


def export_csv(r: BacktestReport, findings: list[ReportFinding]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    if r.status != "approved":
        w.writerow([DRAFT_MARK])
    w.writerow(
        [
            "period_start",
            "period_end",
            "version",
            "status",
            "qualifying_amount",
            "findings_amount",
            "not_received_amount",
            "unverified_amount",
        ]
    )
    w.writerow(
        [
            r.period_start,
            r.period_end,
            r.version_no,
            r.status,
            r.qualifying_amount,
            r.findings_amount,
            r.not_received_amount,
            r.unverified_amount,
        ]
    )
    w.writerow([])
    w.writerow(
        [
            "section",
            "type",
            "vendor",
            "document",
            "date",
            "po",
            "line",
            "item_code",
            "amount",
            "qualifying",
            "paid_status",
            "status",
            "resolution",
        ]
    )
    for f in findings:
        sn = f.snapshot
        w.writerow(
            [
                _cell(x)
                for x in (
                    f.section,
                    f.type,
                    sn.get("vendor_name"),
                    sn.get("doc_number"),
                    sn.get("doc_date"),
                    sn.get("po_number"),
                    sn.get("line_no"),
                    sn.get("supplier_item_code"),
                    f.amount,
                    f.qualifying,
                    f.paid_status,
                    sn.get("status"),
                    sn.get("resolution_code"),
                )
            ]
        )
    return buf.getvalue().encode()


def export_pdf(r: BacktestReport, findings: list[ReportFinding]) -> bytes:
    sec = r.totals.get("sections", {})
    lines = [
        f"MatchDesk back-test report  {r.period_start} to {r.period_end}  version {r.version_no}  ({r.status})",
        f"Data cut-off: {r.data_cutoff_at.isoformat()}   History read from: {r.history_read_from or 'n/a'}",
        "",
        f"Qualifying total (refund criterion): {r.qualifying_amount}",
        f"Findings: {r.findings_amount}   Not received: {r.not_received_amount}   Unverified: {r.unverified_amount}",
        f"Waived (still counted): {sec.get('waived', {}).get('amount', '0.00')}   Open: {sec.get('open', {}).get('amount', '0.00')}",
        f"Receipt coverage: {r.receipt_coverage_pct}%  class A complete-log coverage: {r.coverage_class_a_pct}%"
        f"  class B: {r.coverage_class_b_pct}%  supplier-slip-only lines: {r.class_c_only_lines}",
        "",
        "Section       Type                 Document       PO       Line   Amount     Paid",
    ]
    for f in findings:
        sn = f.snapshot
        lines.append(
            f"{f.section:<13} {f.type:<20} {str(sn.get('doc_number') or '')[:14]:<14} "
            f"{str(sn.get('po_number') or '')[:8]:<8} {sn.get('line_no') or ''!s:<6} {f.amount!s:>10} {f.paid_status}"
        )
    mark = None if r.status == "approved" else DRAFT_MARK
    return text_pdf(
        lines, title=f"Back-test {r.period_start} to {r.period_end} v{r.version_no}", watermark=mark
    )
