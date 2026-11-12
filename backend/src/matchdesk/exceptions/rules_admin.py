"""Alias map and tolerances (T-4.1.1 (d), T-4.2.4, T-4.2.5; MH-06, MH-10).

An alias whose conversion is not one-to-one (factor not 1, or different units) is created pending
and needs the controller (``approvals``); a retired alias keeps its row with ``valid_to`` and
reason. Every change requests a re-match of the invoices that used the alias or carry its code.
Tolerances are versioned: a change closes the current row and inserts a new one, so old results
keep their rule reference; there is no receipt tolerance anywhere (MH-07).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ConflictError, dec
from matchdesk.exceptions.inputs import build_match_input
from matchdesk.exceptions.models import Approval, ItemAlias, LineMatch, MatchRun, ToleranceRule
from matchdesk.exceptions.triggers import request_runs
from matchdesk.intake.models import InvoiceLineRow, InvoiceRow
from matchdesk.matching import (
    Alias,
    AliasStatus,
    ExceptionType,
    Tolerance,
    alias_converts,
    evaluate,
    normalise_code,
)
from matchdesk.qbo.models import Item
from matchdesk.tenancy import lock_for_update

TOLERANCE_FIELDS = ("qty_tolerance", "price_tol_abs", "price_tol_pct", "charge_allowance")


def describe_alias(a: ItemAlias) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "vendor_id": str(a.vendor_id),
        "supplier_item_code": a.supplier_item_code,
        "supplier_description": a.supplier_description,
        "item_id": str(a.item_id),
        "supplier_uom": a.supplier_uom,
        "item_uom": a.item_uom,
        "conversion_factor": str(a.conversion_factor),
        "status": a.status,
        "approved_by": str(a.approved_by) if a.approved_by else None,
        "valid_from": a.valid_from.isoformat() if a.valid_from else None,
        "valid_to": a.valid_to.isoformat() if a.valid_to else None,
        "retire_reason": a.retire_reason,
        "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
        "version": a.version,
    }


def invoices_for_alias_code(
    s: Session, vendor_id: uuid.UUID, code_norm: str, alias_id: uuid.UUID | None
) -> list:
    """Invoices whose current result used the alias, plus every invoice of the vendor with a line
    carrying the code (lines stopped at ``alias_unconfirmed`` have no alias reference yet)."""
    ids: set[uuid.UUID] = set()
    if alias_id is not None:
        ids |= set(
            s.scalars(
                select(InvoiceLineRow.invoice_id)
                .join(LineMatch, LineMatch.invoice_line_id == InvoiceLineRow.id)
                .where(LineMatch.alias_id == alias_id, LineMatch.is_current.is_(True))
            ).all()
        )
    for inv_id, code in s.execute(
        select(InvoiceLineRow.invoice_id, InvoiceLineRow.supplier_item_code)
        .join(InvoiceRow, InvoiceRow.id == InvoiceLineRow.invoice_id)
        .where(InvoiceRow.vendor_id == vendor_id)
    ).all():
        if normalise_code(code) == code_norm:
            ids.add(inv_id)
    return sorted(ids)


def create_alias(
    s: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    vendor_id: uuid.UUID,
    supplier_item_code: str,
    item_id: uuid.UUID,
    conversion_factor: Decimal,
    supplier_uom: str | None,
    item_uom: str | None,
    supplier_description: str | None = None,
) -> tuple[ItemAlias, Approval | None, MatchRun | None]:
    factor = dec(str(conversion_factor))
    if factor <= 0:
        raise ValueError("conversion factor must be positive")
    norm = normalise_code(supplier_item_code)
    if not norm:
        raise ValueError("supplier item code is empty")
    probe = Alias(
        id="new",
        vendor_id=str(vendor_id),
        supplier_item_code=supplier_item_code,
        item_id=str(item_id),
        status=AliasStatus.PENDING_APPROVAL,
        conversion_factor=factor,
        supplier_uom=supplier_uom,
        item_uom=item_uom,
    )
    converts = alias_converts(probe)
    if s.scalar(
        select(ItemAlias.id).where(
            ItemAlias.vendor_id == vendor_id,
            ItemAlias.supplier_item_code_norm == norm,
            ItemAlias.status.in_(("pending_approval", "active")),
        )
    ):
        raise ConflictError("this supplier code already has a live alias; retire it first")
    alias = ItemAlias(
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        supplier_item_code=supplier_item_code,
        supplier_item_code_norm=norm,
        supplier_description=supplier_description,
        item_id=item_id,
        supplier_uom=supplier_uom,
        item_uom=item_uom,
        conversion_factor=factor,
        status="pending_approval" if converts else "active",
        created_by=user_id,
        version=1,
    )
    s.add(alias)
    s.flush()
    approval = None
    if converts:
        approval = Approval(
            tenant_id=tenant_id,
            subject_type="alias_conversion",
            alias_id=alias.id,
            requested_by=user_id,
            status="pending",
            version=1,
        )
        s.add(approval)
        s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="alias.created",
        entity_type="item_alias",
        entity_id=alias.id,
        after={"status": alias.status, "factor": str(factor)},
    )
    run = (
        None
        if converts
        else request_runs(
            s, tenant_id, invoices_for_alias_code(s, vendor_id, norm, None), "alias_change", alias.id
        )
    )
    return alias, approval, run


def rematch_for_alias(s: Session, tenant_id: uuid.UUID, alias: ItemAlias) -> MatchRun | None:
    ids = invoices_for_alias_code(s, alias.vendor_id, alias.supplier_item_code_norm, alias.id)
    return request_runs(s, tenant_id, ids, "alias_change", alias.id)


def retire_alias(
    s: Session, alias: ItemAlias, user_id: uuid.UUID, reason: str, expected_version: int
) -> MatchRun | None:
    if not reason.strip():
        raise ValueError("a reason is required")
    lock_for_update(s, alias)  # B3/B4 review M3
    if alias.version != expected_version:
        raise ConflictError("stale version")
    if alias.status == "retired":
        return None
    alias.status, alias.valid_to, alias.retire_reason = "retired", datetime.now(UTC), reason.strip()
    alias.version += 1
    s.flush()
    for ap in s.scalars(select(Approval).where(Approval.alias_id == alias.id, Approval.status == "pending")):
        ap.status, ap.version = "withdrawn", ap.version + 1
    write_audit(
        s,
        alias.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="alias.retired",
        entity_type="item_alias",
        entity_id=alias.id,
        after={"reason": alias.retire_reason},
    )
    return rematch_for_alias(s, alias.tenant_id, alias)


def suggestions(
    s: Session, vendor_id: uuid.UUID, code: str, description: str | None, limit: int = 5
) -> list[dict]:
    """Exact code first (an earlier alias of this vendor, or an item SKU), then items by trigram
    similarity of the description (T-4.1.1 (d)). A suggestion is never applied without a person."""
    norm = normalise_code(code)
    out: list[dict] = []
    seen: set[uuid.UUID] = set()
    for a in s.scalars(
        select(ItemAlias)
        .where(ItemAlias.vendor_id == vendor_id, ItemAlias.supplier_item_code_norm == norm)
        .order_by(ItemAlias.created_at.desc())
    ):
        if a.item_id not in seen:
            seen.add(a.item_id)
            out.append({"item_id": str(a.item_id), "basis": "earlier_alias", "score": "1.00"})
    for it in s.scalars(select(Item)):
        if it.id not in seen and norm and normalise_code(it.sku) == norm:
            seen.add(it.id)
            out.append({"item_id": str(it.id), "basis": "sku", "score": "1.00"})
    if description:
        rows = s.execute(
            select(Item.id, func.similarity(Item.name, description).label("sim"))
            .where(text("items.name % :d").bindparams(d=description))
            .order_by(text("sim desc"))
            .limit(limit)
        ).all()
        for item_id, sim in rows:
            if item_id not in seen:
                seen.add(item_id)
                out.append(
                    {
                        "item_id": str(item_id),
                        "basis": "description_similarity",
                        "score": f"{Decimal(str(sim)).quantize(Decimal('0.01'))}",
                    }
                )
    names = {
        i.id: i.name
        for i in s.scalars(select(Item).where(Item.id.in_([uuid.UUID(o["item_id"]) for o in out])))
    }
    for o in out:
        o["item_name"] = names.get(uuid.UUID(o["item_id"]))
    return out[:limit]


def current_tolerances(s: Session) -> list[ToleranceRule]:
    return list(s.scalars(select(ToleranceRule).where(ToleranceRule.valid_to.is_(None))))


def describe_tolerance(t: ToleranceRule | None, vendor_id: uuid.UUID | None = None) -> dict[str, Any]:
    if t is None:
        d = Tolerance()
        return {
            "id": None,
            "vendor_id": str(vendor_id) if vendor_id else None,
            "is_default_rule_set": True,
            **{f: str(getattr(d, f)) for f in TOLERANCE_FIELDS},
            "receipt_tolerance": None,
        }
    return {
        "id": str(t.id),
        "vendor_id": str(t.vendor_id) if t.vendor_id else None,
        **{f: str(getattr(t, f)) for f in TOLERANCE_FIELDS},
        "valid_from": t.valid_from.isoformat(),
        "valid_to": t.valid_to.isoformat() if t.valid_to else None,
        # There is no tolerance for an absent receipt, by design (MH-07).
        "receipt_tolerance": None,
    }


def _affected_invoices(s: Session, vendor_id: uuid.UUID | None) -> list[uuid.UUID]:
    q = select(InvoiceRow.id)
    if vendor_id is not None:
        q = q.where(InvoiceRow.vendor_id == vendor_id)
    return sorted(s.scalars(q).all())


def set_tolerance(
    s: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    values: dict[str, Decimal],
) -> tuple[ToleranceRule, MatchRun | None]:
    unknown = set(values) - set(TOLERANCE_FIELDS)
    if unknown:
        raise ValueError("unknown tolerance fields: " + ", ".join(sorted(unknown)))
    now = datetime.now(UTC)
    q = select(ToleranceRule).where(ToleranceRule.valid_to.is_(None))
    q = (
        q.where(ToleranceRule.vendor_id == vendor_id)
        if vendor_id
        else q.where(ToleranceRule.vendor_id.is_(None))
    )
    current = s.scalar(q.with_for_update())
    base = (
        {f: getattr(current, f) for f in TOLERANCE_FIELDS}
        if current
        else {f: getattr(Tolerance(), f) for f in TOLERANCE_FIELDS}
    )
    base.update({k: dec(str(v)) for k, v in values.items()})
    if current is not None:
        current.valid_to = now
        s.flush()
    rule = ToleranceRule(tenant_id=tenant_id, vendor_id=vendor_id, valid_from=now, created_by=user_id, **base)
    s.add(rule)
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="tolerance.changed",
        entity_type="tolerance_rule",
        entity_id=rule.id,
        before={
            f: str(v)
            for f, v in (
                {} if current is None else {f: getattr(current, f) for f in TOLERANCE_FIELDS}
            ).items()
        },
        after={f: str(base[f]) for f in TOLERANCE_FIELDS},
    )
    run = request_runs(s, tenant_id, _affected_invoices(s, vendor_id), "tolerance_change", rule.id)
    return rule, run


def preview_tolerance(s: Session, vendor_id: uuid.UUID | None, values: dict[str, Decimal]) -> dict[str, int]:
    """Count lines a change would re-match and how many exceptions would no longer be raised. Pure
    evaluation over the current inputs; nothing is written."""
    ids = _affected_invoices(s, vendor_id)
    if not ids:
        return {"lines_rematched": 0, "exceptions_now": 0, "exceptions_after": 0, "exceptions_cleared": 0}
    inp = build_match_input(s, ids)
    before = evaluate(inp)
    cur = (
        inp.default_tolerance
        if vendor_id is None
        else dict(inp.vendor_tolerances).get(str(vendor_id), inp.default_tolerance)
    )
    proposed = dataclasses.replace(cur, **{k: dec(str(v)) for k, v in values.items()}, rule_id=None)
    if vendor_id is None:
        changed = dataclasses.replace(inp, default_tolerance=proposed)
    else:
        rest = tuple((v, t) for v, t in inp.vendor_tolerances if v != str(vendor_id))
        changed = dataclasses.replace(inp, vendor_tolerances=(*rest, (str(vendor_id), proposed)))
    after = evaluate(changed)
    tol_types = {
        ExceptionType.QTY_OVER_RECEIVED,
        ExceptionType.QTY_OVER_ORDERED,
        ExceptionType.PRICE_VARIANCE,
        ExceptionType.UNMATCHED_CHARGE,
    }
    n_before = sum(1 for e in before.exceptions if e.type in tol_types)
    n_after = sum(1 for e in after.exceptions if e.type in tol_types)
    return {
        "lines_rematched": len(before.lines),
        "exceptions_now": n_before,
        "exceptions_after": n_after,
        "exceptions_cleared": max(n_before - n_after, 0),
    }
