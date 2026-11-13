"""Invoice list, extraction review and confirmation; batch status and retry (TRD 12; T-3.3.1,
T-3.3.3; B3). Wiring only."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, literal, select

from matchdesk.api import paging, views
from matchdesk.api.common import Auth, StaleVersion, if_match, page_limit, require
from matchdesk.core import NotFoundError
from matchdesk.exceptions import related_invoices, request_runs
from matchdesk.intake import (
    DISPLAYED,
    VersionConflict,
    batch_summary,
    confirm,
    correct,
    describe_fields,
    retry_failed,
)
from matchdesk.intake.models import DocumentRow, InvoiceRow, UploadBatch
from matchdesk.tenancy import session


class Correction(BaseModel):
    draft: bool = False
    fields: dict[str, Any] = Field(default_factory=dict)
    lines: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class ConfirmBody(BaseModel):
    accept_inconsistent: bool = False
    # Required with accept_inconsistent when the figures do not add up (S-07; B9).
    note: str | None = Field(default=None, max_length=2000)


def _summary(
    inv: InvoiceRow, state: str | None, vendors: dict[uuid.UUID, str] | None = None
) -> dict[str, Any]:
    return {
        "vendor_name": (vendors or {}).get(inv.vendor_id) if inv.vendor_id else None,
        "id": str(inv.id),
        "document_id": str(inv.document_id),
        "doc_type": inv.doc_type,
        "doc_number": inv.doc_number,
        "doc_date": inv.doc_date.isoformat() if inv.doc_date else None,
        "vendor_id": str(inv.vendor_id) if inv.vendor_id else None,
        "po_number": inv.po_number_read,
        "total": str(inv.total) if inv.total is not None else None,
        "verification_status": inv.verification_status,
        "document_state": state,
        "displayed_state": DISPLAYED.get(state or "", None),
        "version": inv.version,
    }


# Documents without a date sort last and without a number first within their date.
INVOICE_ORDER = (
    func.coalesce(InvoiceRow.doc_date, literal(date(9999, 12, 31))),
    func.coalesce(InvoiceRow.doc_number, literal("")),
    InvoiceRow.id,
)
INVOICE_PARSERS = (paging.AS_DATE, paging.AS_TEXT, paging.AS_UUID)


def register_invoice_routes(app: FastAPI, engine: Engine) -> None:
    @app.get("/api/v1/invoices")
    def list_invoices(
        p: Auth,
        cursor: str | None = None,
        limit: int | None = None,
        verification_status: str | None = None,
        document_state: str | None = None,
        vendor_id: uuid.UUID | None = None,
        doc_type: str | None = None,
    ) -> dict[str, Any]:
        require(p, "read")
        n = page_limit(limit)
        with session(p.tenant_id, engine) as s:
            q = select(InvoiceRow, DocumentRow.state).join(
                DocumentRow,
                (DocumentRow.id == InvoiceRow.document_id) & (DocumentRow.tenant_id == InvoiceRow.tenant_id),
            )
            if verification_status:
                q = q.where(InvoiceRow.verification_status == verification_status)
            if document_state:
                q = q.where(DocumentRow.state == document_state)
            if vendor_id:
                q = q.where(InvoiceRow.vendor_id == vendor_id)
            if doc_type:  # B10: S-13 asked for credit notes; the filter was ignored
                q = q.where(InvoiceRow.doc_type == doc_type)
            # B10: the order S-06 shows (document date, then number, then id), paged by that key.
            q = paging.keyset(q, INVOICE_ORDER, INVOICE_PARSERS, cursor, n)
            shown, nxt = paging.page(s.execute(q).all(), len(INVOICE_ORDER), n)
            names = views.vendor_names(s)
            return {"items": [_summary(inv, st, names) for inv, st in shown], "next_cursor": nxt}

    @app.patch("/api/v1/invoices/{invoice_id}/extraction")
    def patch_extraction(
        invoice_id: uuid.UUID,
        body: Correction,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "correct_extraction")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            inv = s.get(InvoiceRow, invoice_id)
            if inv is None:
                raise NotFoundError("invoice")
            try:
                correct(s, inv, p.user_id, version, body.fields, body.lines, body.draft)
            except VersionConflict as exc:
                raise StaleVersion(exc.current) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return describe_fields(s, inv)

    @app.post("/api/v1/invoices/{invoice_id}/confirm-extraction")
    def post_confirm(
        invoice_id: uuid.UUID,
        p: Auth,
        body: ConfirmBody | None = None,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "correct_extraction")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            inv = s.get(InvoiceRow, invoice_id)
            if inv is None:
                raise NotFoundError("invoice")
            try:
                inv, gates = confirm(
                    s,
                    inv,
                    p.user_id,
                    version,
                    bool(body and body.accept_inconsistent),
                    body.note if body else None,
                )
            except VersionConflict as exc:
                raise StaleVersion(exc.current) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            # The corrected document re-enters matching with every invoice on its purchase orders.
            run = request_runs(
                s, p.tenant_id, related_invoices(s, [inv.id]), "document_ready", inv.document_id
            )
            return {
                "id": str(inv.id),
                "verification_status": inv.verification_status,
                "inconsistent_note": inv.inconsistent_note,
                "gates": gates,
                "version": inv.version,
                "match_run_id": str(run.id) if run else None,
            }

    @app.get("/api/v1/intake/batches")
    def list_batches(p: Auth, cursor: uuid.UUID | None = None, limit: int | None = None) -> dict[str, Any]:
        require(p, "read")
        n = page_limit(limit)
        with session(p.tenant_id, engine) as s:
            q = select(UploadBatch).order_by(UploadBatch.id).limit(n + 1)
            if cursor is not None:
                q = q.where(UploadBatch.id > cursor)
            rows = s.scalars(q).all()
            return {
                "items": [
                    {
                        "id": str(b.id),
                        "source": b.source,
                        "file_count": b.file_count,
                        "created_at": b.created_at.isoformat(),
                        "totals": batch_summary(s, b.id),
                    }
                    for b in rows[:n]
                ],
                "next_cursor": str(rows[n - 1].id) if len(rows) > n else None,
            }

    @app.get("/api/v1/intake/batches/{batch_id}")
    def get_batch(batch_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            batch = s.get(UploadBatch, batch_id)
            if batch is None:
                raise NotFoundError("batch")
            docs = s.scalars(
                select(DocumentRow)
                .where(DocumentRow.batch_id == batch.id)
                .order_by(DocumentRow.created_at, DocumentRow.id)
            ).all()
            invoices: dict[uuid.UUID, list[InvoiceRow]] = {}
            for inv in s.scalars(
                select(InvoiceRow)
                .where(InvoiceRow.document_id.in_([d.id for d in docs]))
                .order_by(InvoiceRow.page_from)
            ):
                invoices.setdefault(inv.document_id, []).append(inv)
            vendors = views.vendor_names(s)
            # The first document read from the original of each duplicate file, for the link to it
            # (App-flow S-06), wherever its batch.
            originals = {d.duplicate_of_document_id for d in docs if d.duplicate_of_document_id}
            original_invoice: dict[uuid.UUID, uuid.UUID] = {}
            for inv in s.scalars(
                select(InvoiceRow)
                .where(InvoiceRow.document_id.in_(originals))
                .order_by(InvoiceRow.page_from.desc())
            ):
                original_invoice[inv.document_id] = inv.id
            return {
                "id": str(batch.id),
                "created_at": batch.created_at.isoformat(),
                "totals": batch_summary(s, batch.id),
                "files": [
                    {
                        "id": str(d.id),
                        "state": d.state,
                        "displayed_state": DISPLAYED[d.state],
                        "failure_code": d.failure_code,
                        "byte_size": d.byte_size,
                        "mime_type": d.mime_type,
                        "duplicate_of_document_id": str(d.duplicate_of_document_id)
                        if d.duplicate_of_document_id
                        else None,
                        "duplicate_of_invoice_id": str(original_invoice[d.duplicate_of_document_id])
                        if d.duplicate_of_document_id in original_invoice
                        else None,
                        "original_name": d.original_name,
                        "invoices": [
                            {
                                "id": str(i.id),
                                "doc_type": i.doc_type,
                                "doc_number": i.doc_number,
                                "vendor_name": vendors.get(i.vendor_id) if i.vendor_id else None,
                                "verification_status": i.verification_status,
                            }
                            for i in invoices.get(d.id, [])
                        ],
                    }
                    for d in docs
                ],
            }

    @app.post("/api/v1/intake/batches/{batch_id}/retry-failed")
    def post_retry(batch_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        require(p, "upload_and_receiving")
        with session(p.tenant_id, engine) as s:
            if s.get(UploadBatch, batch_id) is None:
                raise NotFoundError("batch")
            return {"requeued": retry_failed(s, p.tenant_id, batch_id)}
