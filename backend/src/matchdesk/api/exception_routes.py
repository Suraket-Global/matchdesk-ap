"""Exception queue, resolutions, approvals, alias map and tolerances (TRD 12; T-4.2.1, T-4.2.3 to
T-4.2.5 back end; T-4.1.1 (d) suggestions; B3). Wiring only: rules live in ``exceptions``."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from matchdesk import receiving
from matchdesk.api import queue, views
from matchdesk.api.common import (
    Auth,
    StaleVersion,
    body_hash,
    idempotent_replay,
    if_match,
    page_limit,
    remember,
    require,
)
from matchdesk.audit import write_audit
from matchdesk.core import NotFoundError
from matchdesk.exceptions import (
    INPUT_DECISIONS,
    StaleExceptionVersion,
    allowed_codes,
    bulk_resolve,
    create_alias,
    current_tolerances,
    decide,
    describe_alias,
    describe_tolerance,
    invoices_for_alias_code,
    invoices_on_po_lines,
    preview_tolerance,
    related_invoices,
    rematch_for_alias,
    reopen,
    request_runs,
    resolve,
    retire_alias,
    set_tolerance,
    stale_runs,
    suggestions,
    withdraw,
)
from matchdesk.exceptions.models import (
    Approval,
    ExceptionEvent,
    ExceptionRow,
    ItemAlias,
    LineMatch,
    ToleranceRule,
)
from matchdesk.identity import Membership, Principal, Tenant
from matchdesk.intake.models import InvoiceLineRow, InvoiceRow
from matchdesk.matching import normalise_code
from matchdesk.tenancy import session


class ResolutionBody(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=2000)


class BulkItem(BaseModel):
    id: uuid.UUID
    version: int


class BulkBody(BaseModel):
    items: list[BulkItem] = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=2000)


class DecisionBody(BaseModel):
    decision: Literal["approve", "return"]
    note: str | None = Field(default=None, max_length=2000)


class AliasBody(BaseModel):
    vendor_id: uuid.UUID
    supplier_item_code: str = Field(min_length=1, max_length=100)
    item_id: uuid.UUID
    conversion_factor: Decimal = Decimal("1")
    supplier_uom: str | None = Field(default=None, max_length=20)
    item_uom: str | None = Field(default=None, max_length=20)
    supplier_description: str | None = Field(default=None, max_length=500)


class RetireBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ToleranceBody(BaseModel):
    qty_tolerance: Decimal | None = None
    price_tol_abs: Decimal | None = None
    price_tol_pct: Decimal | None = None
    charge_allowance: Decimal | None = None
    waiver_limit: Decimal | None = None
    waiver_period_cap: Decimal | None = None


class PreviewBody(ToleranceBody):
    vendor_id: uuid.UUID | None = None


def exception_body(e: ExceptionRow, stale: bool | None = None) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "invoice_id": str(e.invoice_id),
        "invoice_line_id": str(e.invoice_line_id) if e.invoice_line_id else None,
        "type": e.type,
        "sub_reason": e.sub_reason,
        "status": e.status,
        "value_class": e.value_class,
        "qualifying": e.qualifying,
        "resolution_code": e.resolution_code,
        "resolution_note": e.resolution_note,
        "resolved_by": str(e.resolved_by) if e.resolved_by else None,
        "variance_qty": str(e.variance_qty) if e.variance_qty is not None else None,
        "variance_amount": str(e.variance_amount) if e.variance_amount is not None else None,
        "reported_amount": str(e.reported_amount) if e.reported_amount is not None else None,
        "possibly_credited": e.possibly_credited_bill_id is not None,
        "label": e.label,
        "allowed_codes": sorted(allowed_codes(e)),
        "stale": stale,
        "version": e.version,
    }


def _approval_body(a: Approval) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "subject_type": a.subject_type,
        "exception_id": str(a.exception_id) if a.exception_id else None,
        "alias_id": str(a.alias_id) if a.alias_id else None,
        "receiving_import_id": str(a.receiving_import_id) if a.receiving_import_id else None,
        "reason": a.reason,
        "amount": str(a.amount) if a.amount is not None else None,
        "requested_by": str(a.requested_by),
        "status": a.status,
        "decided_by": str(a.decided_by) if a.decided_by else None,
        "decision_note": a.decision_note,
        "self_approved": a.self_approved,
        "version": a.version,
    }


def _approval_context(s: Session, rows: list[Approval]) -> list[dict[str, Any]]:
    """Approvals with the words the S-12 dialogs restate (DD-09): who asked, and the subject."""
    names = views.user_names(s, [a.requested_by for a in rows] + [a.decided_by for a in rows])
    excs = {
        e.id: e
        for e in s.scalars(
            select(ExceptionRow).where(ExceptionRow.id.in_([a.exception_id for a in rows if a.exception_id]))
        )
    }
    ctx = views.exception_context(s, list(excs.values()))
    aliases = {
        a.id: a
        for a in s.scalars(
            select(ItemAlias).where(ItemAlias.id.in_([a.alias_id for a in rows if a.alias_id]))
        )
    }
    vendors = views.vendor_names(s)
    from matchdesk.qbo.models import Item

    items = dict(s.execute(select(Item.id, Item.sku)).all())
    out = []
    for a in rows:
        body = _approval_body(a)
        body["requested_by_name"] = names.get(a.requested_by)
        body["decided_by_name"] = names.get(a.decided_by) if a.decided_by else None
        body["requested_at"] = a.created_at.isoformat()
        e = excs.get(a.exception_id) if a.exception_id else None
        if e is not None:
            body["exception"] = {**exception_body(e), **ctx[e.id]}
        al = aliases.get(a.alias_id) if a.alias_id else None
        if al is not None:
            body["alias"] = {
                **describe_alias(al),
                "vendor_name": vendors.get(al.vendor_id),
                "item_sku": items.get(al.item_id),
            }
            body["affected"] = _alias_affected(s, al)
        out.append(body)
    return out


def _alias_affected(s: Session, al: ItemAlias) -> list[dict[str, Any]]:
    """B8 S-12: the invoice lines a conversion re-matches, with the quantity before and after
    conversion and the exceptions open on them now, so the consequence is read before approval."""
    inv_ids = invoices_for_alias_code(s, al.vendor_id, al.supplier_item_code_norm, al.id)
    if not inv_ids:
        return []
    invoices = {i.id: i for i in s.scalars(select(InvoiceRow).where(InvoiceRow.id.in_(inv_ids)))}
    lines = [
        ln
        for ln in s.scalars(
            select(InvoiceLineRow)
            .where(InvoiceLineRow.invoice_id.in_(inv_ids))
            .order_by(InvoiceLineRow.invoice_id, InvoiceLineRow.line_no)
        )
        if ln.supplier_item_code and normalise_code(ln.supplier_item_code) == al.supplier_item_code_norm
    ]
    open_excs: dict[uuid.UUID, list[str]] = {}
    for e in s.scalars(
        select(ExceptionRow).where(
            ExceptionRow.invoice_line_id.in_([ln.id for ln in lines]),
            ExceptionRow.status.in_(("open", "pending_approval")),
        )
    ):
        if e.invoice_line_id is not None:
            open_excs.setdefault(e.invoice_line_id, []).append(e.type)
    out = []
    for ln in lines:
        inv = invoices[ln.invoice_id]
        out.append(
            {
                "invoice_id": str(inv.id),
                "invoice_line_id": str(ln.id),
                "doc_number": inv.doc_number,
                "doc_date": inv.doc_date.isoformat() if inv.doc_date else None,
                "line_no": ln.line_no,
                "qty": str(ln.qty) if ln.qty is not None else None,
                "uom": ln.uom,
                "converted_qty": str(ln.qty * al.conversion_factor) if ln.qty is not None else None,
                "open_exceptions": sorted(open_excs.get(ln.id, [])),
            }
        )
    return out


def _limits(s: Session, tenant_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    t = s.get(Tenant, tenant_id)
    assert t is not None
    return t.waiver_limit, t.waiver_period_cap


def _controllers(s: Session) -> int:
    return int(
        s.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.role == "controller", Membership.status == "active")
        )
        or 0
    )


def _rematch_after(s: Session, p: Principal, exc: ExceptionRow, code: str) -> str | None:
    if code not in INPUT_DECISIONS:
        return None
    trigger = "manual" if code == "confirmed_not_received" else "duplicate_decision"
    run = request_runs(s, p.tenant_id, related_invoices(s, [exc.invoice_id]), trigger, exc.id)
    return str(run.id) if run else None


def _stale_map(s: Session, rows: list[ExceptionRow]) -> dict[uuid.UUID, bool]:
    lm_ids = [e.line_match_id for e in rows if e.line_match_id]
    runs = dict(s.execute(select(LineMatch.id, LineMatch.match_run_id).where(LineMatch.id.in_(lm_ids))).all())
    stale = stale_runs(s, list(set(runs.values())))
    return {e.id: bool(stale.get(runs.get(e.line_match_id))) for e in rows if e.line_match_id}  # type: ignore[arg-type]


def register_exception_routes(app: FastAPI, engine: Engine) -> None:
    def _filter(
        status: str | None,
        type: str | None,
        value_class: str | None,
        vendor_id: str | None,
        invoice_id: uuid.UUID | None,
        qualifying: bool | None,
        resolved_since: datetime | None,
        period_start: date | None,
        period_end: date | None,
        min_value: str | None,
        max_value: str | None,
        sort: str | None,
        sub_reason: str | None = None,
    ) -> queue.QueueFilter:
        return queue.QueueFilter(
            status=status,
            type=type,
            sub_reason=sub_reason,
            value_class=value_class,
            vendor=vendor_id,
            invoice_id=invoice_id,
            qualifying=qualifying,
            resolved_since=resolved_since,
            period_start=period_start,
            period_end=period_end,
            min_value=queue.parse_decimal(min_value, "min_value"),
            max_value=queue.parse_decimal(max_value, "max_value"),
            sort=sort or "value",
        )

    @app.get("/api/v1/exceptions")
    def list_exceptions(
        p: Auth,
        cursor: str | None = None,
        limit: int | None = None,
        status: str | None = None,
        type: str | None = None,
        value_class: str | None = None,
        vendor_id: str | None = None,
        invoice_id: uuid.UUID | None = None,
        qualifying: bool | None = None,
        resolved_since: datetime | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
        min_value: str | None = None,
        max_value: str | None = None,
        sort: str | None = None,
        sub_reason: str | None = None,
    ) -> dict[str, Any]:
        """S-08 (B8): filters and sort on the whole tenant-scoped set before the page is cut."""
        require(p, "read")
        n = page_limit(limit)
        f = _filter(
            status,
            type,
            value_class,
            vendor_id,
            invoice_id,
            qualifying,
            resolved_since,
            period_start,
            period_end,
            min_value,
            max_value,
            sort,
            sub_reason,
        )
        with session(p.tenant_id, engine) as s:
            result = queue.page(s, f, n, cursor)
            rows = result.pop("items")
            stale = _stale_map(s, rows)
            context = views.exception_context(s, rows)
            return {
                "items": [{**exception_body(e, stale.get(e.id)), **context[e.id]} for e in rows],
                **result,
            }

    @app.get("/api/v1/exceptions/{exception_id}/neighbours")
    def exception_neighbours(
        exception_id: uuid.UUID,
        p: Auth,
        status: str | None = None,
        type: str | None = None,
        vendor_id: str | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
        min_value: str | None = None,
        max_value: str | None = None,
        sort: str | None = None,
    ) -> dict[str, Any]:
        """Previous and next exception in the queue the user opened (S-09, B8), same filters."""
        require(p, "read")
        f = _filter(
            status,
            type,
            None,
            vendor_id,
            None,
            None,
            None,
            period_start,
            period_end,
            min_value,
            max_value,
            sort,
        )
        with session(p.tenant_id, engine) as s:
            exc = _one(s, exception_id)
            near = queue.neighbours(s, f, exc)
            items = [e for e in (near["previous"], near["next"]) if e is not None]
            context = views.exception_context(s, items)

            def brief(e: ExceptionRow | None) -> dict[str, Any] | None:
                if e is None:
                    return None
                c = context[e.id]
                return {
                    "id": str(e.id),
                    "invoice_id": str(e.invoice_id),
                    "invoice_line_id": str(e.invoice_line_id) if e.invoice_line_id else None,
                    "doc_number": c["doc_number"],
                    "type": e.type,
                }

            return {
                "previous": brief(near["previous"]),
                "next": brief(near["next"]),
                "position": near["position"],
                "total": near["total"],
            }

    @app.get("/api/v1/exceptions/{exception_id}/events")
    def exception_events(exception_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            if s.get(ExceptionRow, exception_id) is None:
                raise NotFoundError("exception")
            evs = s.scalars(
                select(ExceptionEvent)
                .where(ExceptionEvent.exception_id == exception_id)
                .order_by(ExceptionEvent.created_at, ExceptionEvent.id)
            ).all()
            return {
                "items": [
                    {
                        "event": e.event,
                        "from_status": e.from_status,
                        "to_status": e.to_status,
                        "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
                        "match_run_id": str(e.match_run_id) if e.match_run_id else None,
                        "detail": e.detail,
                        "at": e.created_at.isoformat(),
                    }
                    for e in evs
                ]
            }

    def _one(s: Session, exception_id: uuid.UUID) -> ExceptionRow:
        e = s.get(ExceptionRow, exception_id)
        if e is None:
            raise NotFoundError("exception")
        return e

    @app.post("/api/v1/exceptions/{exception_id}/resolutions")
    def post_resolution(
        exception_id: uuid.UUID,
        body: ResolutionBody,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "resolve_exception")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            e = _one(s, exception_id)
            limit_, cap = _limits(s, p.tenant_id)
            try:
                out = resolve(s, e, p.user_id, p.role, body.code, body.note, version, limit_, cap)
            except StaleExceptionVersion as exc:
                raise StaleVersion(exception_body(exc.current)) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            run_id = _rematch_after(s, p, e, body.code) if out.rematch else None
            return {
                **exception_body(e),
                "result": out.result,
                "reason": out.reason,
                "approval_id": str(out.approval_id) if out.approval_id else None,
                "match_run_id": run_id,
            }

    @app.post("/api/v1/exceptions/bulk-resolutions")
    def post_bulk(
        body: BulkBody,
        p: Auth,
        response: Response,
        idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
    ) -> dict[str, Any]:
        require(p, "resolve_exception")
        h = body_hash(body.model_dump(mode="json"))
        with session(p.tenant_id, engine) as s:
            if idempotency_key and idempotent_replay(s, p, idempotency_key, h) is not None:
                # A retry of an applied request (same key, same body) answers with what happened,
                # read from the exceptions now, instead of an error (B3/B4 review W8).
                now_rows = {
                    e.id: e
                    for e in s.scalars(
                        select(ExceptionRow).where(ExceptionRow.id.in_([i.id for i in body.items]))
                    )
                }
                replay = []
                for i in body.items:
                    e = now_rows.get(i.id)
                    st = e.status if e is not None else "missing"
                    done = st in ("resolved", "waived", "pending_approval")
                    replay.append(
                        {
                            "id": str(i.id),
                            "result": st if done else "skipped",
                            "reason": None if done else f"status {st}",
                        }
                    )
                return {"results": replay, "replayed": True}
            limit_, cap = _limits(s, p.tenant_id)
            try:
                results = bulk_resolve(
                    s,
                    [(i.id, i.version) for i in body.items],
                    p.user_id,
                    p.role,
                    body.code,
                    body.note,
                    limit_,
                    cap,
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            for r in results:
                if r.get("rematch"):
                    _rematch_after(s, p, _one(s, uuid.UUID(r["id"])), body.code)
            if idempotency_key:
                remember(s, p, idempotency_key, h, 200, "exception", body.items[0].id)
            return {"results": results}

    @app.post("/api/v1/exceptions/{exception_id}/withdraw")
    def post_withdraw(
        exception_id: uuid.UUID,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "withdraw_own_resolution")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            e = _one(s, exception_id)
            try:
                withdraw(s, e, p.user_id, version)
            except StaleExceptionVersion as exc:
                raise StaleVersion(exception_body(exc.current)) from None
            return exception_body(e)

    @app.post("/api/v1/exceptions/{exception_id}/reopen")
    def post_reopen(
        exception_id: uuid.UUID,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "reopen_exception")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            e = _one(s, exception_id)
            try:
                reopen(s, e, p.user_id, p.role, version)
            except StaleExceptionVersion as exc:
                raise StaleVersion(exception_body(exc.current)) from None
            return exception_body(e)

    @app.get("/api/v1/approvals")
    def list_approvals(p: Auth, status: str = "pending", subject_type: str | None = None) -> dict[str, Any]:
        require(p, "approve")
        with session(p.tenant_id, engine) as s:
            q = select(Approval).where(Approval.status == status).order_by(Approval.created_at, Approval.id)
            if subject_type:
                q = q.where(Approval.subject_type == subject_type)
            rows = list(s.scalars(q).all())
            return {"items": _approval_context(s, rows)}

    @app.post("/api/v1/approvals/{approval_id}/decision")
    def post_decision(
        approval_id: uuid.UUID,
        body: DecisionBody,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "approve")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            a = s.get(Approval, approval_id)
            if a is None:
                raise NotFoundError("approval")
            if a.version != version:
                raise StaleVersion(_approval_body(a))
            d = decide(
                s, a, p.user_id, p.role, body.decision == "approve", body.note, version, _controllers(s)
            )
            run = None
            if d.effect == "alias_activated":
                alias = s.get(ItemAlias, d.subject_id)
                assert alias is not None
                run = rematch_for_alias(s, p.tenant_id, alias)
            elif d.effect == "late_receipt_approved":
                lines = receiving.approve_late_lines(s, d.subject_id)
                run = request_runs(
                    s, p.tenant_id, invoices_on_po_lines(s, lines), "late_receipt_approval", d.subject_id
                )
            return {**_approval_body(a), "effect": d.effect, "match_run_id": str(run.id) if run else None}

    @app.get("/api/v1/aliases")
    def list_aliases(
        p: Auth, vendor_id: uuid.UUID | None = None, status: str | None = None
    ) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            q = select(ItemAlias).order_by(ItemAlias.supplier_item_code_norm, ItemAlias.created_at)
            if vendor_id:
                q = q.where(ItemAlias.vendor_id == vendor_id)
            if status:
                q = q.where(ItemAlias.status == status)
            rows = list(s.scalars(q).all())
            vendors = views.vendor_names(s)
            from matchdesk.qbo.models import Item

            items = {i.id: i for i in s.scalars(select(Item))}
            names = views.user_names(s, [a.created_by for a in rows] + [a.approved_by for a in rows])
            return {
                "items": [
                    {
                        **describe_alias(a),
                        "vendor_name": vendors.get(a.vendor_id),
                        "item_sku": items[a.item_id].sku if a.item_id in items else None,
                        "item_name": items[a.item_id].name if a.item_id in items else None,
                        "created_by_name": names.get(a.created_by),
                        "approved_by_name": names.get(a.approved_by) if a.approved_by else None,
                    }
                    for a in rows
                ]
            }

    @app.get("/api/v1/aliases/suggestions")
    def alias_suggestions(
        p: Auth, vendor_id: uuid.UUID, code: str, description: str | None = None
    ) -> dict[str, Any]:
        require(p, "edit_alias")
        with session(p.tenant_id, engine) as s:
            return {"items": suggestions(s, vendor_id, code, description)}

    @app.post("/api/v1/aliases", status_code=201)
    def post_alias(
        body: AliasBody,
        p: Auth,
        response: Response,
        idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
    ) -> dict[str, Any]:
        require(p, "edit_alias")
        h = body_hash(body.model_dump(mode="json"))
        with session(p.tenant_id, engine) as s:
            seen = idempotent_replay(s, p, idempotency_key, h)
            if seen is not None:
                alias = s.get(ItemAlias, seen[1])
                assert alias is not None
                response.status_code = 200
                return describe_alias(alias)
            try:
                alias, approval, run = create_alias(
                    s,
                    p.tenant_id,
                    p.user_id,
                    body.vendor_id,
                    body.supplier_item_code,
                    body.item_id,
                    body.conversion_factor,
                    body.supplier_uom,
                    body.item_uom,
                    body.supplier_description,
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            remember(s, p, idempotency_key, h, 201, "item_alias", alias.id)
            return {
                **describe_alias(alias),
                "approval_id": str(approval.id) if approval else None,
                "match_run_id": str(run.id) if run else None,
            }

    @app.post("/api/v1/aliases/{alias_id}/deactivate")
    def post_retire(
        alias_id: uuid.UUID,
        body: RetireBody,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "edit_alias")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            alias = s.get(ItemAlias, alias_id)
            if alias is None:
                raise NotFoundError("alias")
            if alias.version != version:
                raise StaleVersion(describe_alias(alias))
            run = retire_alias(s, alias, p.user_id, body.reason, version)
            return {**describe_alias(alias), "match_run_id": str(run.id) if run else None}

    @app.post("/api/v1/aliases/review-acknowledgement")
    def post_ack(p: Auth) -> dict[str, Any]:
        require(p, "approve")
        with session(p.tenant_id, engine) as s:
            rows = s.scalars(
                select(ItemAlias).where(
                    ItemAlias.status == "active",
                    ItemAlias.approved_by.is_(None),
                    ItemAlias.reviewed_at.is_(None),
                )
            ).all()
            now = datetime.now(UTC)
            for a in rows:
                a.reviewed_by, a.reviewed_at = p.user_id, now  # W5: the list empties
            ids = [str(a.id) for a in rows]
            write_audit(
                s,
                p.tenant_id,
                actor_type="user",
                actor_user_id=p.user_id,
                action="aliases.reviewed",
                entity_type="item_alias",
                after={"alias_ids": ids},
            )
            return {"acknowledged": len(ids)}

    @app.get("/api/v1/tolerances")
    def get_tolerances(p: Auth) -> dict[str, Any]:
        require(p, "read_tolerances")
        with session(p.tenant_id, engine) as s:
            current = current_tolerances(s)
            default = next((t for t in current if t.vendor_id is None), None)
            history = s.scalars(
                select(ToleranceRule).order_by(ToleranceRule.valid_from.desc()).limit(100)
            ).all()
            limit_, cap = _limits(s, p.tenant_id)
            return {
                "default": describe_tolerance(default),
                "vendors": [describe_tolerance(t) for t in current if t.vendor_id is not None],
                "history": [describe_tolerance(t) for t in history],
                "waiver_limit": str(limit_),
                "waiver_period_cap": str(cap),
                "receipt_note": "A missing receiving record is always an exception. There is no tolerance for it.",
            }

    @app.put("/api/v1/tolerances/{vendor}")
    def put_tolerance(vendor: str, body: ToleranceBody, p: Auth) -> dict[str, Any]:
        require(p, "edit_tolerances")
        vendor_id = None if vendor == "default" else _uuid(vendor)
        values = {
            k: v
            for k, v in body.model_dump(exclude={"waiver_limit", "waiver_period_cap"}).items()
            if v is not None
        }
        with session(p.tenant_id, engine) as s:
            if vendor_id is not None:
                from matchdesk.qbo.models import Vendor

                if s.get(Vendor, vendor_id) is None:
                    raise NotFoundError("vendor")
            out: dict[str, Any] = {}
            if body.waiver_limit is not None or body.waiver_period_cap is not None:
                if vendor_id is not None:
                    raise HTTPException(
                        422, "the waiver limit and cap are account settings: use /tolerances/default"
                    )
                t = s.get(Tenant, p.tenant_id)
                assert t is not None
                before = {"waiver_limit": str(t.waiver_limit), "waiver_period_cap": str(t.waiver_period_cap)}
                if body.waiver_limit is not None:
                    t.waiver_limit = body.waiver_limit
                if body.waiver_period_cap is not None:
                    t.waiver_period_cap = body.waiver_period_cap
                if t.waiver_limit < 0 or t.waiver_period_cap < t.waiver_limit:
                    raise HTTPException(422, "the cap must be at least the limit, and both at least 0")
                write_audit(
                    s,
                    p.tenant_id,
                    actor_type="user",
                    actor_user_id=p.user_id,
                    action="waiver_limits.changed",
                    entity_type="tenant",
                    entity_id=p.tenant_id,
                    before=before,
                    after={
                        "waiver_limit": str(t.waiver_limit),
                        "waiver_period_cap": str(t.waiver_period_cap),
                    },
                )
                out.update(
                    {"waiver_limit": str(t.waiver_limit), "waiver_period_cap": str(t.waiver_period_cap)}
                )
            if values:
                try:
                    rule, run = set_tolerance(s, p.tenant_id, p.user_id, vendor_id, values)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from None
                out.update(
                    {"tolerance": describe_tolerance(rule), "match_run_id": str(run.id) if run else None}
                )
            return out

    @app.post("/api/v1/tolerances/preview")
    def post_preview(body: PreviewBody, p: Auth) -> dict[str, Any]:
        require(p, "edit_tolerances")
        values = {
            k: v
            for k, v in body.model_dump(exclude={"waiver_limit", "waiver_period_cap", "vendor_id"}).items()
            if v is not None
        }
        with session(p.tenant_id, engine) as s:
            return preview_tolerance(s, body.vendor_id, values)


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise NotFoundError("vendor") from None
