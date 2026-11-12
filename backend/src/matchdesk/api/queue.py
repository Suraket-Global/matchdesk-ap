"""The exception queue S-08 as one ordered set (B8 financial-trust fix).

Every supported filter and the sort order are applied in the database to the whole tenant-scoped
set before a page is cut, so a page never depends on which rows happened to be loaded. The order is
total: each sort ends on the exception id, and the cursor is the last row's full sort key (keyset
pagination), so equal values never repeat or skip a row across pages. Values are compared as
``NUMERIC`` in the database and travel as decimal strings; no float is involved.

The same filters drive the match view's previous and next exception (``neighbours``), so "Next
exception" follows exactly the ordered set the user opened.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy import ColumnElement, Select, case, func, literal, select, tuple_
from sqlalchemy.orm import Session

from matchdesk.exceptions.models import ExceptionRow
from matchdesk.intake.models import InvoiceRow
from matchdesk.qbo.models import Vendor

SORTS = ("value", "age", "vendor")


@dataclass(frozen=True)
class QueueFilter:
    status: str | None = None
    type: str | None = None
    sub_reason: str | None = None
    value_class: str | None = None
    vendor: str | None = None  # a vendor id, or "none" for documents without an identified supplier
    invoice_id: uuid.UUID | None = None
    qualifying: bool | None = None
    resolved_since: datetime | None = None
    period_start: date | None = None
    period_end: date | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    sort: str = "value"
    assignee: str | None = None  # a member's user id, or "none" for unassigned (B9)


def parse_decimal(text: str | None, name: str) -> Decimal | None:
    if text is None or text.strip() == "":
        return None
    try:
        value = Decimal(text.strip().replace(",", ""))
    except InvalidOperation:
        raise HTTPException(422, f"{name} must be an amount such as 100.00") from None
    if not value.is_finite():
        raise HTTPException(422, f"{name} must be an amount such as 100.00")
    return value


def value_expr() -> ColumnElement[Decimal]:
    """The queue's value: the amount counted for the line, else the variance (as S-14 counts it)."""
    return func.coalesce(ExceptionRow.reported_amount, ExceptionRow.variance_amount, literal(Decimal("0")))


def _key_columns(sort: str) -> list[Any]:
    if sort == "age":
        return [ExceptionRow.created_at, ExceptionRow.id]
    if sort == "vendor":
        return [
            case((Vendor.name.is_(None), 1), else_=0),
            func.coalesce(Vendor.name, ""),
            ExceptionRow.id,
        ]
    # Highest value first: ascending on the negated value keeps every key column ascending.
    return [-value_expr(), ExceptionRow.id]


def base_query(f: QueueFilter, with_type: bool = True) -> Select[Any]:
    """Every filter except the cursor, joined to the invoice and supplier for scope and sort."""
    if f.sort not in SORTS:
        raise HTTPException(422, f"sort must be one of {', '.join(SORTS)}")
    q = (
        select(ExceptionRow)
        .join(InvoiceRow, InvoiceRow.id == ExceptionRow.invoice_id)
        .outerjoin(Vendor, Vendor.id == InvoiceRow.vendor_id)
    )
    if f.status:
        q = q.where(ExceptionRow.status.in_(f.status.split(",")))
    if with_type and f.type:
        q = q.where(ExceptionRow.type.in_(f.type.split(",")))
    if f.sub_reason:
        q = q.where(ExceptionRow.sub_reason.in_(f.sub_reason.split(",")))
    if f.value_class:
        q = q.where(ExceptionRow.value_class == f.value_class)
    if f.invoice_id:
        q = q.where(ExceptionRow.invoice_id == f.invoice_id)
    if f.qualifying is not None:
        q = q.where(ExceptionRow.qualifying.is_(f.qualifying))
    if f.resolved_since is not None:
        q = q.where(ExceptionRow.resolved_at >= f.resolved_since)
    if f.vendor == "none":
        q = q.where(InvoiceRow.vendor_id.is_(None))
    elif f.vendor:
        try:
            q = q.where(InvoiceRow.vendor_id == uuid.UUID(f.vendor))
        except ValueError:
            raise HTTPException(422, "vendor_id must be a supplier id or none") from None
    # The scope's dates: documents dated in it (the test month, or the weekly summary's week).
    if f.period_start:
        q = q.where(InvoiceRow.doc_date >= f.period_start)
    if f.period_end:
        q = q.where(InvoiceRow.doc_date <= f.period_end)
    if f.assignee == "none":
        q = q.where(ExceptionRow.assigned_to.is_(None))
    elif f.assignee:
        try:
            q = q.where(ExceptionRow.assigned_to == uuid.UUID(f.assignee))
        except ValueError:
            raise HTTPException(422, "assignee must be a member id, me or none") from None
    if f.min_value is not None:
        q = q.where(value_expr() >= f.min_value)
    if f.max_value is not None:
        q = q.where(value_expr() <= f.max_value)
    return q


def _encode(values: list[Any]) -> str:
    raw = json.dumps([str(v) if v is not None else None for v in values]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str, sort: str) -> list[Any]:
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if sort == "age":
            return [datetime.fromisoformat(raw[0]), uuid.UUID(raw[1])]
        if sort == "vendor":
            return [int(raw[0]), str(raw[1]), uuid.UUID(raw[2])]
        return [Decimal(raw[0]), uuid.UUID(raw[1])]
    except (ValueError, TypeError, IndexError, KeyError, InvalidOperation, json.JSONDecodeError):
        raise HTTPException(422, "cursor is not valid for this sort; reload the first page") from None


def _key_of(s: Session, exc: ExceptionRow, sort: str) -> list[Any]:
    cols = _key_columns(sort)
    row = s.execute(
        select(*cols)
        .select_from(ExceptionRow)
        .join(InvoiceRow, InvoiceRow.id == ExceptionRow.invoice_id)
        .outerjoin(Vendor, Vendor.id == InvoiceRow.vendor_id)
        .where(ExceptionRow.id == exc.id)
    ).one()
    return list(row)


def page(s: Session, f: QueueFilter, limit: int, cursor: str | None) -> dict[str, Any]:
    """One page of the ordered set, the set's count and value, and per-type and per-status counts."""
    q = base_query(f)
    cols = _key_columns(f.sort)
    scoped = q.subquery()
    total_count, total_value = s.execute(
        select(
            func.count(),
            func.coalesce(func.sum(func.coalesce(scoped.c.reported_amount, scoped.c.variance_amount)), 0),
        )
    ).one()
    counters = dict(
        s.execute(q.with_only_columns(ExceptionRow.status, func.count()).group_by(ExceptionRow.status)).all()
    )
    # Type counters ignore the type filter, so each counter says what choosing it would show.
    type_counters = dict(
        s.execute(
            base_query(f, with_type=False)
            .with_only_columns(ExceptionRow.type, func.count())
            .group_by(ExceptionRow.type)
        ).all()
    )
    page_q = q.add_columns(*cols).order_by(*cols).limit(limit + 1)
    if cursor:
        page_q = page_q.where(tuple_(*cols) > tuple_(*[literal(v) for v in _decode(cursor, f.sort)]))
    rows = s.execute(page_q).all()
    items = [r[0] for r in rows[:limit]]
    nxt = _encode(list(rows[limit - 1][1:])) if len(rows) > limit else None
    return {
        "items": items,
        "counters": counters,
        "type_counters": type_counters,
        "total_count": int(total_count),
        "total_value": str(Decimal(total_value).quantize(Decimal("0.01"))),
        "next_cursor": nxt,
    }


def neighbours(s: Session, f: QueueFilter, exc: ExceptionRow) -> dict[str, Any]:
    """The exceptions before and after ``exc`` in the ordered set, and its position. Works when
    ``exc`` has just left the set (resolved): the neighbours are taken around its sort key."""
    q = base_query(f)
    cols = _key_columns(f.sort)
    key = tuple_(*[literal(v) for v in _key_of(s, exc, f.sort)])
    after = s.scalars(q.where(tuple_(*cols) > key).order_by(*cols).limit(1)).first()
    before = s.scalars(q.where(tuple_(*cols) < key).order_by(*[c.desc() for c in cols]).limit(1)).first()
    position = s.scalar(q.with_only_columns(func.count()).where(tuple_(*cols) < key).order_by(None))
    total = s.scalar(q.with_only_columns(func.count()).order_by(None))
    in_set = s.scalar(q.with_only_columns(func.count()).where(ExceptionRow.id == exc.id).order_by(None))
    return {
        "previous": before,
        "next": after,
        "position": int(position or 0) + 1 if in_set else None,
        "total": int(total or 0),
    }
