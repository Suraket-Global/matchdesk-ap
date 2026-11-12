"""Sync runs: idempotent, resumable read of QuickBooks into the local copies (T-3.1.2 (a) to (d);
TRD 6.3; IT-04, UT-14). Read only: nothing is ever written to QuickBooks.

One page is one transaction: the rows of the page are upserted on (tenant, QuickBooks id) and the
cursor is saved with them, so a worker killed after page 1 resumes at page 2 and a repeated run
creates no duplicates. Bills and vendor credits of the synced vendors are read with no date filter,
so earlier invoices on an in-scope purchase order still count (AD-13). A disconnected tenant gets
no sync (self-check 6.4).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ConflictError, dec, get_correlation_id, get_logger, new_correlation_id
from matchdesk.matching import normalise_number
from matchdesk.qbo.client import ENTITIES, PageQuery, QboNotConfiguredError, QboReader
from matchdesk.qbo.models import (
    Item,
    PoLineChange,
    PoLineRow,
    PurchaseOrderRow,
    QboBillLineRow,
    QboBillRow,
    QboConnection,
    SyncRun,
    Vendor,
)
from matchdesk.qbo.oauth import get_connection, processing_allowed
from matchdesk.tenancy import PermanentJobError, enqueue, session, transition

log = get_logger("matchdesk.qbo.sync")
TASK = "qbo_sync"
MATCH_REQUEST_TASK = "match_request"  # handled by ``exceptions`` (qbo does not import it)
PENDING = ("queued", "running", "retry_wait")
LEASE = timedelta(minutes=10)


def scope_fingerprint(mode: str, start: date | None, end: date | None, refs: list[str] | None) -> bytes:
    key = f"{mode}|{start}|{end}|" + ",".join(sorted(refs or []))
    return hashlib.sha256(key.encode()).digest()


def request_sync(
    s: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    mode: str,
    range_start: date | None = None,
    range_end: date | None = None,
    references: list[str] | None = None,
) -> tuple[SyncRun, bool]:
    """Queue a sync; idempotent on (tenant, scope) while one is pending. Returns (run, created)."""
    conn = get_connection(s)
    if conn is None or conn.status != "connected" or not processing_allowed(s):
        raise ConflictError("QuickBooks is not connected")
    if mode == "date_range" and (range_start is None or range_end is None or range_end < range_start):
        raise ValueError("a date-range sync needs a start and an end")
    if mode == "po_references" and not references:
        raise ValueError("a purchase-order sync needs at least one reference")
    refs = sorted({r.strip() for r in references or [] if r.strip()}) if mode == "po_references" else None
    fp = scope_fingerprint(mode, range_start, range_end, refs)
    found = s.scalar(select(SyncRun).where(SyncRun.scope_fingerprint == fp, SyncRun.state.in_(PENDING)))
    if found is not None:
        return found, False
    corr = get_correlation_id() or new_correlation_id()
    run = SyncRun(
        tenant_id=tenant_id,
        mode=mode,
        range_start=range_start if mode == "date_range" else None,
        range_end=range_end if mode == "date_range" else None,
        po_references=refs,
        scope_fingerprint=fp,
        correlation_id=uuid.UUID(corr),
        requested_by=user_id,
        cursor={},
        counts={},
    )
    s.add(run)
    s.flush()
    enqueue(s, TASK, tenant_id, {"sync_run_id": str(run.id)}, corr)
    return run, True


def _take(engine: Engine, tenant_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    with session(tenant_id, engine) as s:
        run = s.get(SyncRun, run_id)
        if run is None:
            raise PermanentJobError("sync run not found in this tenant")
        now = datetime.now(UTC)
        expired = run.state == "running" and run.lease_expires_at is not None and run.lease_expires_at < now
        if run.state not in ("queued", "retry_wait") and not expired:
            return run.state == "running"  # same worker retrying inside its lease
        return transition(
            s,
            "sync_runs",
            run.id,
            run.state_version,
            "running",
            lease_expires_at=now + LEASE,
            started_at=run.started_at or now,
        )


def _finish(engine: Engine, tenant_id: uuid.UUID, run_id: uuid.UUID, state: str, error: str | None) -> None:
    with session(tenant_id, engine) as s:
        run = s.get(SyncRun, run_id)
        if run is None or run.state != "running":
            return
        transition(
            s,
            "sync_runs",
            run.id,
            run.state_version,
            state,
            lease_expires_at=None,
            error_code=error,
            finished_at=datetime.now(UTC),
        )


def execute_sync(
    engine: Engine, tenant_id: uuid.UUID, run_id: uuid.UUID, reader: QboReader, page_size: int
) -> str:
    """Run (or resume) one sync. Each page commits its rows and the cursor together."""
    if not _take(engine, tenant_id, run_id):
        return "skipped"
    while True:
        try:
            with session(tenant_id, engine) as s:
                run = s.get(SyncRun, run_id)
                assert run is not None
                if run.state != "running":
                    return run.state
                if not processing_allowed(s):
                    raise ConflictError("QuickBooks was disconnected")
                done = _one_page(s, tenant_id, run, reader, page_size)
        except (QboNotConfiguredError, ConflictError) as exc:
            _finish(engine, tenant_id, run_id, "failed", type(exc).__name__)
            raise PermanentJobError(str(exc)) from exc
        except Exception:
            with session(tenant_id, engine) as s:
                run = s.get(SyncRun, run_id)
                if run is not None and run.state == "running":
                    transition(s, "sync_runs", run.id, run.state_version, "retry_wait", lease_expires_at=None)
            raise  # the job wrapper retries with backoff; the cursor is kept
        if done:
            break
    with session(tenant_id, engine) as s:
        run = s.get(SyncRun, run_id)
        assert run is not None
        conn = s.scalar(select(QboConnection))
        if conn is not None:
            conn.last_success_at = datetime.now(UTC)
        po_ids = sorted(run.cursor.get("po_ids", []))
        if po_ids:
            enqueue(
                s,
                MATCH_REQUEST_TASK,
                tenant_id,
                {"po_ids": po_ids, "trigger": "po_change", "trigger_ref": str(run.id)},
                str(run.correlation_id),
            )
        write_audit(
            s,
            tenant_id,
            actor_type="job",
            action="qbo.sync_succeeded",
            entity_type="sync_run",
            entity_id=run.id,
            after={"counts": run.counts},
        )
    _finish(engine, tenant_id, run_id, "succeeded", None)
    return "succeeded"


def _query(run: SyncRun, entity: str) -> PageQuery:
    if entity == "PurchaseOrder":
        if run.mode == "po_references":
            return PageQuery(references=tuple(run.po_references or []))
        return PageQuery(since=run.range_start, until=run.range_end)
    if entity in ("Bill", "VendorCredit"):
        return PageQuery(vendor_ids=tuple(sorted(run.cursor.get("vendor_qbo_ids", []))))
    return PageQuery()


def _one_page(s: Session, tenant_id: uuid.UUID, run: SyncRun, reader: QboReader, size: int) -> bool:
    cursor = dict(run.cursor or {})
    cursor.setdefault("run_id", str(run.id))
    idx = int(cursor.get("entity_index", 0))
    if idx >= len(ENTITIES):
        return True
    entity = ENTITIES[idx]
    start = int(cursor.get("start", 1))
    rows = reader.page(entity, start, size, _query(run, entity))
    now = datetime.now(UTC)
    handler = {
        "Vendor": _vendors,
        "Item": _items,
        "PurchaseOrder": _pos,
        "Bill": _bills,
        "VendorCredit": _bills,
    }[entity]
    handler(s, tenant_id, rows, now, cursor, entity)
    counts = dict(run.counts or {})
    counts[entity] = int(counts.get(entity, 0)) + len(rows)
    if len(rows) < size:
        cursor["entity_index"], cursor["start"] = idx + 1, 1
    else:
        cursor["entity_index"], cursor["start"] = idx, start + size
    cursor.setdefault("pages", 0)
    cursor["pages"] = int(cursor["pages"]) + 1
    run.cursor = cursor
    run.counts = counts
    s.flush()
    return int(cursor["entity_index"]) >= len(ENTITIES)


def _ref(row: dict[str, Any], key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, dict):
        return str(value["value"]) if value.get("value") is not None else None
    return str(value) if value is not None else None


def _d(value: Any) -> Decimal | None:
    return None if value is None else dec(str(value))


def _vendors(
    s: Session, tid: uuid.UUID, rows: list[dict[str, Any]], now: datetime, _c: dict, _e: str
) -> None:
    existing = {
        v.qbo_id: v for v in s.scalars(select(Vendor).where(Vendor.qbo_id.in_([str(r["Id"]) for r in rows])))
    }
    for r in rows:
        v = existing.get(str(r["Id"])) or Vendor(tenant_id=tid, qbo_id=str(r["Id"]))
        v.name = str(r.get("DisplayName") or r.get("CompanyName") or r["Id"])
        v.active = bool(r.get("Active", True))
        v.synced_at = now
        s.add(v)


def _items(s: Session, tid: uuid.UUID, rows: list[dict[str, Any]], now: datetime, _c: dict, _e: str) -> None:
    existing = {
        i.qbo_id: i for i in s.scalars(select(Item).where(Item.qbo_id.in_([str(r["Id"]) for r in rows])))
    }
    for r in rows:
        it = existing.get(str(r["Id"])) or Item(tenant_id=tid, qbo_id=str(r["Id"]))
        it.name = str(r.get("Name") or r["Id"])
        it.sku = r.get("Sku")
        it.purchase_uom = r.get("PurchaseUom") or r.get("UOM")
        it.synced_at = now
        s.add(it)


def _vendor_map(s: Session) -> dict[str, uuid.UUID]:
    return {q: i for q, i in s.execute(select(Vendor.qbo_id, Vendor.id)).all()}


def _item_map(s: Session) -> dict[str, uuid.UUID]:
    return {q: i for q, i in s.execute(select(Item.qbo_id, Item.id)).all()}


def _pos(
    s: Session, tid: uuid.UUID, rows: list[dict[str, Any]], now: datetime, cursor: dict, _e: str
) -> None:
    vendors, items = _vendor_map(s), _item_map(s)
    existing = {
        p.qbo_id: p
        for p in s.scalars(
            select(PurchaseOrderRow).where(PurchaseOrderRow.qbo_id.in_([str(r["Id"]) for r in rows]))
        )
    }
    vendor_qbo = set(cursor.get("vendor_qbo_ids", []))
    po_ids = set(cursor.get("po_ids", []))
    changes: list[tuple[str, PoLineRow, dict[str, Any], dict[str, Any] | None]] = []
    for r in rows:
        vendor_ref = _ref(r, "VendorRef")
        if vendor_ref not in vendors:
            continue  # vendor not read (inactive and filtered): skip rather than guess
        po = existing.get(str(r["Id"])) or PurchaseOrderRow(tenant_id=tid, qbo_id=str(r["Id"]))
        po.vendor_id = vendors[vendor_ref]
        po.po_number = str(r.get("DocNumber") or r["Id"])
        po.po_number_norm = normalise_number(po.po_number)
        po.txn_date = date.fromisoformat(str(r["TxnDate"]))
        po.qbo_status = r.get("POStatus")
        po.total = _d(r.get("TotalAmt"))
        po.qbo_sync_token = r.get("SyncToken")
        po.synced_at = now
        s.add(po)
        s.flush()
        lines = {
            pl.qbo_line_id: pl
            for pl in s.scalars(select(PoLineRow).where(PoLineRow.purchase_order_id == po.id))
        }
        seen: set[str] = set()
        for ln in r.get("Line", []):
            if ln.get("Id") is None:
                continue
            seen.add(str(ln["Id"]))
            known = lines.get(str(ln["Id"]))
            before = _line_values(known) if known is not None and known.removed_at is None else None
            pl = known or PoLineRow(tenant_id=tid, purchase_order_id=po.id, qbo_line_id=str(ln["Id"]))
            pl.removed_at = None
            pl.line_no = int(ln.get("LineNum") or 0)
            pl.description = ln.get("Description")
            pl.amount = _d(ln.get("Amount"))
            detail = ln.get("ItemBasedExpenseLineDetail")
            if detail is not None:
                item_ref = _ref(detail, "ItemRef")
                pl.item_id = items.get(item_ref) if item_ref else None
                pl.qty_ordered = _d(detail.get("Qty")) or Decimal("0")
                pl.unit_price = _d(detail.get("UnitPrice")) or Decimal("0")
                pl.uom = (
                    detail.get("UOMRef", {}).get("value") if isinstance(detail.get("UOMRef"), dict) else None
                )
                pl.charge_kind = None
            else:
                desc = (pl.description or "").lower()
                pl.charge_kind = "freight" if "freight" in desc or "shipping" in desc else "fee"
                pl.qty_ordered = Decimal("1")
                pl.unit_price = pl.amount or Decimal("0")
            s.add(pl)
            if before is not None and before != _line_values(pl):
                changes.append(("changed", pl, before, _line_values(pl)))
        for qbo_line_id, gone in lines.items():
            if qbo_line_id not in seen and gone.removed_at is None:
                gone.removed_at = now  # deleted in QuickBooks: no longer matchable (B3/B4 review m6)
                changes.append(("removed", gone, _line_values(gone), None))
        s.flush()
        for kind, line, old, new in changes:
            # S-10 (B9): what this read changed, kept as history; the po_change re-match follows.
            s.add(
                PoLineChange(
                    tenant_id=tid,
                    purchase_order_id=po.id,
                    po_line_id=line.id,
                    sync_run_id=uuid.UUID(cursor["run_id"]) if cursor.get("run_id") else None,
                    change=kind,
                    before=old,
                    after=new,
                    detected_at=now,
                )
            )
        changes.clear()
        vendor_qbo.add(vendor_ref)
        po_ids.add(str(po.id))
    cursor["vendor_qbo_ids"] = sorted(vendor_qbo)
    cursor["po_ids"] = sorted(po_ids)


def _line_values(pl: PoLineRow) -> dict[str, Any]:
    """The values of a PO line that matching reads, as plain strings (S-10 before and after)."""
    return {
        "line_no": pl.line_no,
        "item_id": str(pl.item_id) if pl.item_id else None,
        "description": pl.description,
        "qty_ordered": _num(pl.qty_ordered),
        "uom": pl.uom,
        "unit_price": _num(pl.unit_price),
    }


def _num(value: Decimal | None) -> str | None:
    """A decimal in its shortest exact form, so 500 read from QuickBooks equals the stored 500.0000."""
    if value is None:
        return None
    return format(dec(value).normalize(), "f")


def _paid(total: Decimal | None, balance: Decimal | None) -> str:
    if balance is None or total is None:
        return "unknown"
    if balance == 0:
        return "paid"
    return "unpaid" if balance >= total else "partly_paid"


def _bills(
    s: Session, tid: uuid.UUID, rows: list[dict[str, Any]], now: datetime, _c: dict, entity: str
) -> None:
    txn_type = "bill" if entity == "Bill" else "vendor_credit"
    vendors = _vendor_map(s)
    po_map = {q: i for q, i in s.execute(select(PurchaseOrderRow.qbo_id, PurchaseOrderRow.id)).all()}
    existing = {
        b.qbo_id: b
        for b in s.scalars(
            select(QboBillRow).where(
                QboBillRow.txn_type == txn_type, QboBillRow.qbo_id.in_([str(r["Id"]) for r in rows])
            )
        )
    }
    for r in rows:
        vendor_ref = _ref(r, "VendorRef")
        if vendor_ref not in vendors:
            continue
        b = existing.get(str(r["Id"])) or QboBillRow(tenant_id=tid, qbo_id=str(r["Id"]), txn_type=txn_type)
        b.vendor_id = vendors[vendor_ref]
        b.doc_number = r.get("DocNumber")
        b.doc_number_norm = normalise_number(b.doc_number) or None
        b.txn_date = date.fromisoformat(str(r["TxnDate"])) if r.get("TxnDate") else None
        b.total = _d(r.get("TotalAmt")) or Decimal("0")
        b.balance = _d(r.get("Balance"))
        b.paid_status = _paid(b.total, b.balance) if txn_type == "bill" else "unknown"
        b.synced_at = now
        s.add(b)
        s.flush()
        # Bill lines have no stable key of their own here: replace them as one unit (idempotent).
        s.execute(delete(QboBillLineRow).where(QboBillLineRow.qbo_bill_id == b.id))
        for ln in r.get("Line", []):
            detail = ln.get("ItemBasedExpenseLineDetail") or {}
            linked = next((t for t in ln.get("LinkedTxn", []) if t.get("TxnType") == "PurchaseOrder"), None)
            po_qbo = str(linked["TxnId"]) if linked else None
            po_line_qbo = str(linked["TxnLineId"]) if linked and linked.get("TxnLineId") is not None else None
            po_line_id = None
            if po_qbo in po_map and po_line_qbo is not None:
                po_line_id = s.scalar(
                    select(PoLineRow.id).where(
                        PoLineRow.purchase_order_id == po_map[po_qbo], PoLineRow.qbo_line_id == po_line_qbo
                    )
                )
            s.add(
                QboBillLineRow(
                    tenant_id=tid,
                    qbo_bill_id=b.id,
                    qbo_line_id=str(ln["Id"]) if ln.get("Id") is not None else None,
                    qty=_d(detail.get("Qty")),
                    unit_price=_d(detail.get("UnitPrice")),
                    amount=_d(ln.get("Amount")) or Decimal("0"),
                    linked_po_qbo_id=po_qbo,
                    linked_po_line_qbo_id=po_line_qbo,
                    po_line_id=po_line_id,
                )
            )


def make_sync_handler(engine: Engine, reader_factory: Any, page_size: int) -> Any:
    def handler(_s: Session, payload: dict[str, Any]) -> None:
        execute_sync(
            engine,
            uuid.UUID(payload["tenant_id"]),
            uuid.UUID(payload["sync_run_id"]),
            reader_factory(),
            page_size,
        )

    return handler


def describe_sync(run: SyncRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "mode": run.mode,
        "range_start": run.range_start.isoformat() if run.range_start else None,
        "range_end": run.range_end.isoformat() if run.range_end else None,
        "po_references": run.po_references,
        "state": run.state,
        "counts": run.counts,
        "pages_read": int((run.cursor or {}).get("pages", 0)),
        "error_code": run.error_code,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
