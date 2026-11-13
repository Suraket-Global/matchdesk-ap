"""B12 routes (wiring only): delete one document (S-06, S-07) and the controller's usage (S-16).
TRD section 12 lists them."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select

from matchdesk import reporting
from matchdesk.api.common import Auth, require
from matchdesk.core import NotFoundError
from matchdesk.exceptions import removal_rule, remove_document
from matchdesk.intake.models import DocumentRow, InvoiceRow
from matchdesk.tenancy import session


class DocumentDeletionBody(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


def _invoices(s: Any, doc: DocumentRow) -> list[InvoiceRow]:
    return list(s.scalars(select(InvoiceRow).where(InvoiceRow.document_id == doc.id)).all())


def register_b12_routes(app: FastAPI, engine: Engine) -> None:
    @app.get("/api/v1/documents/{document_id}/deletion")
    def get_document_deletion(document_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        """What deleting this document needs, and whether it was deleted (C K V)."""
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            doc = s.get(DocumentRow, document_id)
            if doc is None:
                raise NotFoundError("document")
            return {
                **removal_rule(doc, _invoices(s, doc)),
                "removed_at": doc.removed_at.isoformat() if doc.removed_at else None,
                "removed_reason": doc.removed_reason,
            }

    @app.post("/api/v1/documents/{document_id}/deletion-requests")
    def post_document_deletion(document_id: uuid.UUID, body: DocumentDeletionBody, p: Auth) -> dict[str, Any]:
        """Delete one invoice or credit-note document at once (soft; C K, accepted documents C with
        a reason). The suppliers' other documents are re-matched; approved reports are untouched."""
        require(p, "delete_document")
        with session(p.tenant_id, engine) as s:
            doc = s.get(DocumentRow, document_id)
            if doc is None:
                raise NotFoundError("document")
            try:
                return remove_document(s, p.tenant_id, doc, p.user_id, p.role, body.reason)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None

    @app.get("/api/v1/usage")
    def get_usage(p: Auth) -> dict[str, Any]:
        """The account's billable units by month: the operator's figures on S-18, without a price."""
        require(p, "read_usage")
        with session(p.tenant_id, engine) as s:
            items = reporting.usage_by_month(s, p.tenant_id)
        return {
            "items": items,
            "total_units": sum(int(i["units"]) for i in items),
            "unit": "one invoice or credit note, in the month it was first read",
        }
