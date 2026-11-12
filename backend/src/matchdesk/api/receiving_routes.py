"""Receiving imports, class B confirmation and the receiving attestation (TRD 12; T-3.2.1, T-3.2.2).

Wiring only: ``receiving`` changes the evidence, ``exceptions`` raises the late-evidence approval and
requests the re-match, in the same transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Form, Header, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from matchdesk import receiving
from matchdesk.api.common import Auth, body_hash, idempotent_replay, if_match, page_limit, remember, require
from matchdesk.api.limits import MAX_UPLOAD_FILE_BYTES
from matchdesk.core import NotFoundError
from matchdesk.exceptions import (
    invoices_on_po_lines,
    po_lines_with_open_exceptions,
    request_late_receipt_approval,
    request_runs,
)
from matchdesk.intake.models import DocumentRow
from matchdesk.qbo.models import PoLineRow, PurchaseOrderRow
from matchdesk.receiving.models import ReceiptLineRow, ReceiptRow, ReceivingImportRow
from matchdesk.tenancy import session

RECEIVING_MAX_BYTES = 20 * 1024 * 1024


class Declaration(BaseModel):
    declared_complete: bool
    coverage_start: date | None = None
    coverage_end: date | None = None
    kept_by_name: str | None = Field(default=None, max_length=200)


class Mapping(BaseModel):
    columns: dict[str, str]
    save_as: str | None = Field(default=None, max_length=100)


class VoidBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ConfirmBody(BaseModel):
    receiver_marks_present: bool
    receiver_name: str | None = Field(default=None, max_length=200)


class AttestationBody(BaseModel):
    evidence_class: Literal["A", "B", "C"]
    source_description: str = Field(min_length=1, max_length=500)
    ap_staff: list[str] = Field(default_factory=list, max_length=100)


def _load(s: Session, import_id: uuid.UUID) -> ReceivingImportRow:
    imp = s.get(ReceivingImportRow, import_id)
    if imp is None:
        raise NotFoundError("receiving import")
    return imp


def _rematch(
    s: Session, tenant_id: uuid.UUID, po_line_ids: list[uuid.UUID], import_id: uuid.UUID
) -> str | None:
    run = request_runs(s, tenant_id, invoices_on_po_lines(s, po_line_ids), "receiving_import", import_id)
    return str(run.id) if run else None


def _file_names(s: Session, imports: Sequence[ReceivingImportRow]) -> dict[uuid.UUID, str | None]:
    ids = [i.document_id for i in imports]
    return dict(
        s.execute(select(DocumentRow.id, DocumentRow.original_name).where(DocumentRow.id.in_(ids))).all()
    )  # type: ignore[arg-type]


def register_receiving_routes(app: FastAPI, engine: Engine) -> None:
    @app.post("/api/v1/receiving/imports", status_code=201)
    async def post_import(
        p: Auth,
        file: UploadFile,
        evidence_class: Annotated[Literal["A", "B", "C"], Form()],
        source_type: Annotated[
            Literal["spreadsheet", "delivery_document", "qbo_item_receipt_export"], Form()
        ] = "spreadsheet",
        kept_by_name: Annotated[str | None, Form(max_length=200)] = None,
    ) -> dict[str, Any]:
        require(p, "upload_and_receiving")
        data = await file.read(MAX_UPLOAD_FILE_BYTES + 1)
        if len(data) > RECEIVING_MAX_BYTES:
            raise HTTPException(413, "File is larger than 20 MB")
        return await run_in_threadpool(
            _create, p, data, source_type, evidence_class, kept_by_name, file.filename
        )

    def _create(
        p: Any,
        data: bytes,
        source_type: str,
        evidence_class: str,
        kept_by: str | None,
        name: str | None = None,
    ) -> dict[str, Any]:
        try:
            with session(p.tenant_id, engine) as s:
                imp, prev = receiving.create_import(
                    s, p.tenant_id, p.user_id, data, source_type, evidence_class, kept_by, name
                )
                return {**receiving.describe_import(imp), "preview": prev}
        except receiving.ReceivingFileError as exc:
            raise HTTPException(415 if "accepted" in str(exc) else 422, str(exc)) from None

    @app.put("/api/v1/receiving/imports/{import_id}/declaration")
    def put_declaration(import_id: uuid.UUID, body: Declaration, p: Auth) -> dict[str, Any]:
        require(p, "upload_and_receiving")
        with session(p.tenant_id, engine) as s:
            imp = _load(s, import_id)
            try:
                receiving.set_declaration(
                    s,
                    imp,
                    p.user_id,
                    body.declared_complete,
                    body.coverage_start,
                    body.coverage_end,
                    body.kept_by_name,
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            pos = receiving.affected_po_lines(s, imp.id)
            run_id = _rematch(s, p.tenant_id, pos, imp.id) if imp.state == "succeeded" else None
            return {**receiving.describe_import(imp), "match_run_id": run_id}

    @app.put("/api/v1/receiving/imports/{import_id}/mapping")
    def put_mapping(import_id: uuid.UUID, body: Mapping, p: Auth) -> dict[str, Any]:
        require(p, "upload_and_receiving")
        with session(p.tenant_id, engine) as s:
            imp = _load(s, import_id)
            try:
                receiving.save_mapping(s, imp, p.user_id, body.columns, body.save_as)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return {**receiving.describe_import(imp), "validation": receiving.preview(s, imp)}

    @app.post("/api/v1/receiving/imports/{import_id}/commit")
    def post_commit(import_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        require(p, "upload_and_receiving")
        with session(p.tenant_id, engine) as s:
            imp = _load(s, import_id)
            candidate_lines = [pl.id for pl in s.scalars(select(PoLineRow))]
            open_lines = po_lines_with_open_exceptions(s, candidate_lines)
            imp, touched = receiving.commit(s, imp, p.user_id, open_lines)
            late = receiving.late_line_count(s, imp.id)
            approval = request_late_receipt_approval(s, p.tenant_id, imp.id, p.user_id, late)
            run_id = _rematch(s, p.tenant_id, touched, imp.id) if touched else None
            return {
                **receiving.describe_import(imp),
                "late_lines": late,
                "late_approval_id": str(approval.id) if approval else None,
                "match_run_id": run_id,
            }

    @app.post("/api/v1/receiving/imports/{import_id}/void")
    def post_void(import_id: uuid.UUID, body: VoidBody, p: Auth) -> dict[str, Any]:
        require(p, "upload_and_receiving")
        with session(p.tenant_id, engine) as s:
            imp = _load(s, import_id)
            try:
                lines = receiving.void(s, imp, p.user_id, body.reason)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            run_id = _rematch(s, p.tenant_id, lines, imp.id) if lines else None
            return {**receiving.describe_import(imp), "match_run_id": run_id}

    @app.get("/api/v1/receiving/imports")
    def list_imports(p: Auth, cursor: uuid.UUID | None = None, limit: int | None = None) -> dict[str, Any]:
        require(p, "read")
        n = page_limit(limit)
        with session(p.tenant_id, engine) as s:
            q = select(ReceivingImportRow).order_by(ReceivingImportRow.id).limit(n + 1)
            if cursor is not None:
                q = q.where(ReceivingImportRow.id > cursor)
            rows = s.scalars(q).all()
            names = _file_names(s, rows[:n])
            # Rows loaded for lines that already had an open exception, still waiting for the
            # controller (App-flow S-05 column).
            waiting = dict(
                s.execute(
                    select(ReceiptLineRow.receiving_import_id, func.count())
                    .where(
                        ReceiptLineRow.receiving_import_id.in_([i.id for i in rows[:n]]),
                        ReceiptLineRow.added_after_exception.is_(True),
                        ReceiptLineRow.late_approved.is_(False),
                    )
                    .group_by(ReceiptLineRow.receiving_import_id)
                ).all()
            )
            return {
                "items": [
                    {
                        **receiving.describe_import(i),
                        "late_lines_waiting": int(waiting.get(i.id, 0)),
                        "file_name": names.get(i.document_id),
                        "created_at": i.created_at.isoformat(),
                    }
                    for i in rows[:n]
                ],
                "next_cursor": str(rows[n - 1].id) if len(rows) > n else None,
            }

    @app.get("/api/v1/receiving/imports/{import_id}")
    def get_import(import_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            imp = _load(s, import_id)
            receipts = s.scalars(
                select(ReceiptRow)
                .where(ReceiptRow.receiving_import_id == imp.id)
                .order_by(ReceiptRow.received_date, ReceiptRow.id)
            ).all()
            lines = s.scalars(
                select(ReceiptLineRow).where(ReceiptLineRow.receiving_import_id == imp.id)
            ).all()
            by_receipt: dict[uuid.UUID, list[ReceiptLineRow]] = {}
            for ln in lines:
                by_receipt.setdefault(ln.receipt_id, []).append(ln)
            body = receiving.describe_import(imp)
            body["file_name"] = _file_names(s, [imp]).get(imp.document_id)
            if imp.state == "draft":
                body["preview"] = receiving.file_preview(s, imp)
            body["created_at"] = imp.created_at.isoformat()
            po_numbers = dict(
                s.execute(
                    select(PurchaseOrderRow.id, PurchaseOrderRow.po_number).where(
                        PurchaseOrderRow.id.in_({r.purchase_order_id for r in receipts})
                    )
                ).all()
            )
            po_lines = {
                pl.id: pl
                for pl in s.scalars(
                    select(PoLineRow).where(PoLineRow.id.in_({ln.po_line_id for ln in lines}))
                )
            }
            body["receipts"] = [
                {
                    "id": str(r.id),
                    "purchase_order_id": str(r.purchase_order_id),
                    "po_number": po_numbers.get(r.purchase_order_id),
                    "received_date": r.received_date.isoformat(),
                    "receiver_ref": r.receiver_ref,
                    "receiver_marks_present": r.receiver_marks_present,
                    "receiver_name": r.receiver_name,
                    "version": r.version,
                    "lines": [
                        {
                            "id": str(ln.id),
                            "po_line_id": str(ln.po_line_id),
                            "po_line_no": po_lines[ln.po_line_id].line_no
                            if ln.po_line_id in po_lines
                            else None,
                            "uom": ln.uom
                            or (po_lines[ln.po_line_id].uom if ln.po_line_id in po_lines else None),
                            "qty_received": str(ln.qty_received),
                            "source_row": ln.source_row,
                            "added_after_exception": ln.added_after_exception,
                            "late_approved": ln.late_approved,
                        }
                        for ln in sorted(by_receipt.get(r.id, []), key=lambda x: x.source_row)
                    ],
                }
                for r in receipts
            ]
            return body

    @app.post("/api/v1/receiving/receipts/{receipt_id}/confirm")
    def confirm(
        receipt_id: uuid.UUID,
        body: ConfirmBody,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "upload_and_receiving")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            receipt = receiving.confirm_receipt(
                s, receipt_id, p.user_id, version, body.receiver_marks_present, body.receiver_name
            )
            po_lines = s.scalars(
                select(ReceiptLineRow.po_line_id).where(ReceiptLineRow.receipt_id == receipt.id)
            ).all()
            run_id = _rematch(s, p.tenant_id, list(po_lines), receipt.receiving_import_id)
            return {
                "id": str(receipt.id),
                "version": receipt.version,
                "match_run_id": run_id,
                "receiver_marks_present": receipt.receiver_marks_present,
                "receiver_name": receipt.receiver_name,
            }

    @app.post("/api/v1/receiving/attestation", status_code=201)
    def post_attestation(
        body: AttestationBody,
        p: Auth,
        response: Response,
        idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
    ) -> dict[str, Any]:
        require(p, "attest_receiving")
        h = body_hash(body.model_dump())
        with session(p.tenant_id, engine) as s:
            seen = idempotent_replay(s, p, idempotency_key, h)
            if seen is not None:
                response.status_code = 200
                return {"id": str(seen[1])}
            row = receiving.attest(
                s, p.tenant_id, p.user_id, body.evidence_class, body.source_description, body.ap_staff
            )
            remember(s, p, idempotency_key, h, 201, "receiving_attestation", row.id)
            return {"id": str(row.id), "evidence_class": row.evidence_class, "ap_staff": row.ap_staff}
