"""QuickBooks connection, sync runs and purchase-order read copies (TRD 12; T-3.1.1, T-3.1.2; B3).

Wiring only. The OAuth callback is a browser redirect outside ``/api``: it authenticates with the
session cookie itself and validates ``state`` against that session and tenant.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select

from matchdesk.api import views
from matchdesk.api.common import (
    Auth,
    body_hash,
    idempotent_replay,
    money,
    page_limit,
    remember,
    require,
    session_cookie,
)
from matchdesk.core import ConflictError, NotFoundError, Settings
from matchdesk.exceptions import unknown_history
from matchdesk.identity import load_session
from matchdesk.qbo import (
    QboNotConfiguredError,
    QboTransientError,
    TokenEndpoint,
    complete_callback,
    describe_connection,
    describe_sync,
    disconnect,
    get_connection,
    read_company_name,
    request_sync,
    start_authorization,
    tenant_qbo_mode,
    urllib_get,
)
from matchdesk.qbo import Transport as QboTransport
from matchdesk.qbo.models import PoLineRow, PurchaseOrderRow, SyncRun, Vendor
from matchdesk.receiving import counting_receipt_totals
from matchdesk.tenancy import session


class SyncRequest(BaseModel):
    mode: Literal["date_range", "po_references"]
    range_start: date | None = None
    range_end: date | None = None
    po_references: list[str] | None = Field(default=None, max_length=500)


def register_qbo_routes(
    app: FastAPI,
    settings: Settings,
    engine: Engine,
    endpoints: dict[str, TokenEndpoint],
    transport: QboTransport = urllib_get,
) -> None:
    sandbox = "sandbox" in settings.qbo_api_base_url

    @app.get("/api/v1/qbo/connection")
    def get_qbo_connection(p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            # B4: the screen labels recorded-response mode and never sends anyone to Intuit in it.
            # B8: the header and S-04 show the server's last read (success or failure), not a guess.
            # B11: the mode is this tenant's (tenants.qbo_mode, else the server setting).
            mode = tenant_qbo_mode(s, settings, p.tenant_id)
            last = s.scalars(select(SyncRun).order_by(SyncRun.created_at.desc()).limit(1)).first()
            return {
                **describe_connection(get_connection(s)),
                "mode": mode,
                "source": "demo_data" if mode != "intuit" else "intuit",
                "intuit_environment": ("sandbox" if sandbox else "production") if mode == "intuit" else None,
                "last_sync": describe_sync(last) if last else None,
            }

    @app.post("/api/v1/qbo/connection/authorize")
    def authorize(p: Auth) -> dict[str, Any]:
        require(p, "connect_qbo")
        if p.session_id is None:
            raise HTTPException(401, "Not signed in")
        try:
            with session(p.tenant_id, engine) as s:
                url = start_authorization(s, settings, p.tenant_id, p.user_id, p.session_id)
        except QboNotConfiguredError:
            raise HTTPException(503, "QuickBooks connection is not configured on this server") from None
        return {"authorization_url": url}

    @app.get("/oauth/intuit/callback")
    def intuit_callback(request: Request, state: str = "", code: str = "", realmId: str = "") -> Response:
        token = request.cookies.get(session_cookie(settings))
        ctx = load_session(engine, token) if token else None
        p = ctx.principal() if ctx is not None else None
        target = f"{settings.app_base_url}/settings/quickbooks"
        if p is None or p.role != "controller" or not state or not code or not realmId:
            return RedirectResponse(f"{target}?result=refused", status_code=303)
        try:
            with session(p.tenant_id, engine) as s:
                endpoint = endpoints[tenant_qbo_mode(s, settings, p.tenant_id)]
                complete_callback(s, settings, endpoint, p.tenant_id, ctx.session_id, state, code, realmId)  # type: ignore[union-attr]
            mode = tenant_qbo_mode(s, settings, p.tenant_id)
        except (NotFoundError, ConflictError, PermissionError, QboNotConfiguredError, QboTransientError):
            return RedirectResponse(f"{target}?result=refused", status_code=303)
        if mode == "intuit":  # B11: name the company on S-04 (one GET of CompanyInfo)
            read_company_name(engine, settings, p.tenant_id, endpoints["intuit"], transport)
        return RedirectResponse(f"{target}?result=connected", status_code=303)

    @app.delete("/api/v1/qbo/connection")
    def delete_connection(p: Auth) -> dict[str, Any]:
        require(p, "connect_qbo")
        with session(p.tenant_id, engine) as s:
            endpoint = endpoints[tenant_qbo_mode(s, settings, p.tenant_id)]
            return describe_connection(disconnect(s, settings, endpoint, p.tenant_id, p.user_id))

    @app.post("/api/v1/qbo/sync-runs", status_code=202)
    def post_sync(
        body: SyncRequest,
        p: Auth,
        response: Response,
        idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
    ) -> dict[str, Any]:
        require(p, "start_sync")
        h = body_hash(body.model_dump(mode="json"))
        with session(p.tenant_id, engine) as s:
            seen = idempotent_replay(s, p, idempotency_key, h)
            if seen is not None:
                run = s.get(SyncRun, seen[1])
                assert run is not None
                response.status_code = 200
                return describe_sync(run)
            try:
                run, created = request_sync(
                    s, p.tenant_id, p.user_id, body.mode, body.range_start, body.range_end, body.po_references
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            remember(s, p, idempotency_key, h, 202, "sync_run", run.id)
            if not created:
                response.status_code = 200
            return describe_sync(run)

    @app.get("/api/v1/qbo/sync-runs/{run_id}")
    def get_sync(run_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            run = s.get(SyncRun, run_id)
            if run is None:
                raise NotFoundError("sync run")
            return describe_sync(run)

    @app.get("/api/v1/purchase-orders")
    def list_pos(
        p: Auth,
        cursor: uuid.UUID | None = None,
        limit: int | None = None,
        vendor_id: uuid.UUID | None = None,
        po_number: str | None = None,
    ) -> dict[str, Any]:
        require(p, "read")
        n = page_limit(limit)
        with session(p.tenant_id, engine) as s:
            q = select(PurchaseOrderRow).order_by(PurchaseOrderRow.id).limit(n + 1)
            if cursor is not None:
                q = q.where(PurchaseOrderRow.id > cursor)
            if vendor_id is not None:
                q = q.where(PurchaseOrderRow.vendor_id == vendor_id)
            if po_number:
                from matchdesk.matching import normalise_number

                q = q.where(PurchaseOrderRow.po_number_norm == normalise_number(po_number))
            rows = s.scalars(q).all()
            names = dict(s.execute(select(Vendor.id, Vendor.name)).all())
            items = [_po_summary(po, names.get(po.vendor_id)) for po in rows[:n]]
            return {"items": items, "next_cursor": str(rows[n - 1].id) if len(rows) > n else None}

    @app.get("/api/v1/purchase-orders/{po_id}")
    def get_po(po_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            po = s.get(PurchaseOrderRow, po_id)
            if po is None:
                raise NotFoundError("purchase order")
            lines = s.scalars(
                select(PoLineRow).where(PoLineRow.purchase_order_id == po.id).order_by(PoLineRow.line_no)
            ).all()
            received = counting_receipt_totals(s, [ln.id for ln in lines])
            from matchdesk.intake.models import InvoiceRow, live_invoice

            invoice_count = s.scalar(
                select(func.count())
                .select_from(InvoiceRow)
                .where(InvoiceRow.purchase_order_id == po.id, live_invoice())
            )
            vendor = s.get(Vendor, po.vendor_id)
            body = _po_summary(po, vendor.name if vendor else None)
            body["invoice_count"] = int(invoice_count or 0)
            body["lines"] = [
                {
                    "id": str(ln.id),
                    "line_no": ln.line_no,
                    "description": ln.description,
                    "item_id": str(ln.item_id) if ln.item_id else None,
                    "qty_ordered": str(ln.qty_ordered),
                    "uom": ln.uom,
                    "unit_price": str(ln.unit_price),
                    "amount": money(ln.amount),
                    "charge_kind": ln.charge_kind,
                    "removed_at": ln.removed_at.isoformat() if ln.removed_at else None,
                    "qty_received_counting": str(received.get(ln.id, (Decimal("0"), 0))[0]),
                    "counting_receipt_lines": received.get(ln.id, (Decimal("0"), 0))[1],
                }
                for ln in lines
            ]
            body["changed_in_quickbooks"] = views.po_change_banner(s, po.id)
            # B11: why QuickBooks history on this PO is unknown (its lines are history_incomplete).
            body["history_unknown"] = list(unknown_history(s, [po]).get(po.id, ()))
            return body


def _po_summary(po: PurchaseOrderRow, vendor_name: str | None) -> dict[str, Any]:
    return {
        "id": str(po.id),
        "po_number": po.po_number,
        "vendor_id": str(po.vendor_id),
        "vendor_name": vendor_name,
        "txn_date": po.txn_date.isoformat(),
        "qbo_status": po.qbo_status,
        "total": money(po.total),
    }
