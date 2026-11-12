"""B9 routes (wiring only): the "no receiving records" declaration (S-03), removing an invoice line in
review (S-07), saved receiving mappings (S-05), the assignee (S-08), credit and duplicate decisions
(S-09), finding outcomes (S-13), the archive export and the account deletion request (S-16, S-18).
TRD section 12 lists them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select

from matchdesk import blobstore, receiving, reporting
from matchdesk.api import views
from matchdesk.api.b7_routes import operator
from matchdesk.api.common import Auth, Ctx, StaleVersion, if_match, require
from matchdesk.api.exception_routes import exception_body
from matchdesk.audit import write_audit
from matchdesk.core import NotFoundError
from matchdesk.exceptions import (
    DUPLICATE_DECISIONS,
    StaleExceptionVersion,
    assign,
    credit_decision,
    related_invoices,
    request_runs,
    resolve,
    retire_line_result,
)
from matchdesk.exceptions.models import ExceptionRow
from matchdesk.identity import Membership, Tenant
from matchdesk.intake import VersionConflict, describe_fields, remove_line
from matchdesk.intake.models import DocumentRow, InvoiceRow
from matchdesk.reporting.models import ArchiveExport, DeletionRequest, ReportFinding
from matchdesk.tenancy import global_session, operator_session, session


class WithdrawBody(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class RemoveLineBody(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class AssignBody(BaseModel):
    user_id: uuid.UUID | None = None


class CreditBody(BaseModel):
    decision: Literal["credited", "not_credited"]
    note: str | None = Field(default=None, max_length=2000)


class DuplicateBody(BaseModel):
    decision: Literal["is_duplicate", "not_duplicate"]
    note: str | None = Field(default=None, max_length=2000)


class OutcomeBody(BaseModel):
    outcome: Literal["controller_confirmed", "credit_recovered"]
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    credit_invoice_id: uuid.UUID | None = None
    credit_reference: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class DeletionBody(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    # The controller types the account name: the request is not made by a stray click.
    confirm_name: str = Field(min_length=1, max_length=200)


class DeletionDecision(BaseModel):
    decision: Literal["schedule", "decline"]
    note: str | None = Field(default=None, max_length=2000)


def _assignable(s: Any) -> list[tuple[uuid.UUID, str]]:
    """Active controllers and clerks: the people who can work an exception."""
    rows = s.execute(
        select(Membership.user_id, Membership.role).where(
            Membership.status == "active", Membership.role.in_(("controller", "clerk"))
        )
    ).all()
    return [(r[0], r[1]) for r in rows]


def register_b9_routes(app: FastAPI, engine: Engine) -> None:
    # ------------------------------------------------------------------ S-03 no receiving records
    @app.get("/api/v1/onboarding/no-receiving-declaration")
    def get_declaration(p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            row = receiving.current_declaration(s)
            names = views.user_names(s, [row.declared_by] if row else [])
            return {
                "declaration": receiving.describe_declaration(row, names),
                "statement": receiving.NO_RECEIVING_STATEMENT,
            }

    @app.post("/api/v1/onboarding/no-receiving-declaration", status_code=201)
    def post_declaration(p: Auth) -> dict[str, Any]:
        require(p, "attest_receiving")
        with session(p.tenant_id, engine) as s:
            row = receiving.declare_no_receiving(s, p.tenant_id, p.user_id)
            names = views.user_names(s, [row.declared_by])
            return {"declaration": receiving.describe_declaration(row, names)}

    @app.post("/api/v1/onboarding/no-receiving-declaration/withdraw")
    def post_withdraw_declaration(body: WithdrawBody, p: Auth) -> dict[str, Any]:
        require(p, "attest_receiving")
        with session(p.tenant_id, engine) as s:
            row = receiving.current_declaration(s)
            if row is None:
                raise NotFoundError("declaration")
            receiving.withdraw_declaration(s, row, p.user_id, body.reason)
            return {"declaration": None}

    @app.get("/api/v1/onboarding/status")
    def get_onboarding_status(p: Auth) -> dict[str, Any]:
        """S-03 (B9): the controller's receiving attestation with name and date, and the purchase-order
        lines where QuickBooks shows more billed than MatchDesk has documents for ("earlier invoices
        needed"), with the QuickBooks bill numbers to upload."""
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            att = receiving.latest_attestation(s)
            names = views.user_names(s, [att.attested_by] if att else [])
            return {
                "attestation": {
                    "evidence_class": att.evidence_class,
                    "source_description": att.source_description,
                    "attested_by_name": names.get(att.attested_by),
                    "attested_at": att.created_at.isoformat(),
                }
                if att
                else None,
                "earlier_invoices_needed": views.earlier_invoices_needed(s),
            }

    # ------------------------------------------------------------------ S-07 remove a line
    @app.post("/api/v1/invoices/{invoice_id}/lines/{line_id}/removal")
    def post_remove_line(
        invoice_id: uuid.UUID,
        line_id: uuid.UUID,
        body: RemoveLineBody,
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
                inv, gates = remove_line(s, inv, p.user_id, version, line_id, body.reason)
            except VersionConflict as exc:
                raise StaleVersion(exc.current) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            retire_line_result(s, line_id)
            return {**describe_fields(s, inv), "gates": gates}

    # ------------------------------------------------------------------ S-05 saved mappings
    @app.get("/api/v1/receiving/mappings")
    def get_mappings(p: Auth) -> dict[str, Any]:
        require(p, "upload_and_receiving")
        with session(p.tenant_id, engine) as s:
            return {"items": [receiving.describe_mapping(m) for m in receiving.list_mappings(s)]}

    # ------------------------------------------------------------------ S-08 assignee
    @app.get("/api/v1/members")
    def get_members(p: Auth) -> dict[str, Any]:
        """Who an exception can be assigned to: names and roles only (no address)."""
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            rows = _assignable(s)
            names = views.user_names(s, [u for u, _r in rows])
            items = [{"user_id": str(u), "name": names.get(u), "role": r} for u, r in rows]
            return {
                "items": sorted(items, key=lambda i: (str(i["name"] or ""), i["user_id"])),
                "me": str(p.user_id),
            }

    def _one(s: Any, exception_id: uuid.UUID) -> ExceptionRow:
        e = s.get(ExceptionRow, exception_id)
        if e is None:
            raise NotFoundError("exception")
        return e  # type: ignore[no-any-return]

    def _with_context(s: Any, e: ExceptionRow) -> dict[str, Any]:
        return {**exception_body(e), **views.exception_context(s, [e])[e.id]}

    @app.put("/api/v1/exceptions/{exception_id}/assignment")
    def put_assignment(
        exception_id: uuid.UUID,
        body: AssignBody,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "assign_exception")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            e = _one(s, exception_id)
            try:
                assign(s, e, p.user_id, body.user_id, version, [u for u, _r in _assignable(s)])
            except StaleExceptionVersion as exc:
                raise StaleVersion(exception_body(exc.current)) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return _with_context(s, e)

    # ------------------------------------------------------------------ S-09 controller decisions
    @app.post("/api/v1/exceptions/{exception_id}/credit-decision")
    def post_credit_decision(
        exception_id: uuid.UUID,
        body: CreditBody,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "decide_duplicate_or_credit")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            e = _one(s, exception_id)
            try:
                credit_decision(s, e, p.user_id, p.role, body.decision, body.note, version)
            except StaleExceptionVersion as exc:
                raise StaleVersion(exception_body(exc.current)) from None
            run = request_runs(s, p.tenant_id, related_invoices(s, [e.invoice_id]), "manual", e.id)
            return {**_with_context(s, e), "match_run_id": str(run.id) if run else None}

    @app.post("/api/v1/exceptions/{exception_id}/duplicate-decision")
    def post_duplicate_decision(
        exception_id: uuid.UUID,
        body: DuplicateBody,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "decide_duplicate_or_credit")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            e = _one(s, exception_id)
            if e.type != "possible_duplicate":
                raise HTTPException(409, "this exception is not a possible duplicate")
            tenant = s.get(Tenant, p.tenant_id)
            assert tenant is not None
            try:
                resolve(
                    s,
                    e,
                    p.user_id,
                    p.role,
                    DUPLICATE_DECISIONS[body.decision],
                    body.note,
                    version,
                    tenant.waiver_limit,
                    tenant.waiver_period_cap,
                )
            except StaleExceptionVersion as exc:
                raise StaleVersion(exception_body(exc.current)) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            run = request_runs(
                s, p.tenant_id, related_invoices(s, [e.invoice_id]), "duplicate_decision", e.id
            )
            return {**_with_context(s, e), "match_run_id": str(run.id) if run else None}

    # ------------------------------------------------------------------ S-13 finding outcomes
    @app.get("/api/v1/reports/backtest/{report_id}/outcomes")
    def get_outcomes(report_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            outcomes = reporting.outcomes_for(s, report_id)
            people = views.user_names(s, [o.recorded_by for per in outcomes.values() for o in per.values()])
            return {
                "is_governing": reporting.governing_report_id(s) == report_id,
                "totals": reporting.outcome_totals(s, report_id),
                "by_finding": {
                    str(fid): {k: reporting.describe_outcome(o, people) for k, o in per.items()}
                    for fid, per in outcomes.items()
                },
            }

    @app.post("/api/v1/reports/findings/{finding_id}/outcomes", status_code=201)
    def post_outcome(finding_id: uuid.UUID, body: OutcomeBody, p: Auth) -> dict[str, Any]:
        require(p, "record_finding_outcome")
        with session(p.tenant_id, engine) as s:
            f = s.get(ReportFinding, finding_id)
            if f is None:
                raise NotFoundError("finding")
            try:
                row = reporting.record_outcome(
                    s,
                    p.tenant_id,
                    p.user_id,
                    p.role,
                    f,
                    body.outcome,
                    body.amount,
                    body.credit_invoice_id,
                    body.credit_reference,
                    body.note,
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            people = views.user_names(s, [row.recorded_by])
            return {
                "outcome": row.outcome,
                **(reporting.describe_outcome(row, people) or {}),
                "totals": reporting.outcome_totals(s, f.report_id),
            }

    # ------------------------------------------------------------------ archive export (S-16)
    @app.get("/api/v1/exports/archive")
    def get_archives(p: Auth) -> dict[str, Any]:
        require(p, "request_deletion_or_archive")
        with session(p.tenant_id, engine) as s:
            rows = s.scalars(select(ArchiveExport).order_by(ArchiveExport.created_at.desc()).limit(5)).all()
            return {"items": [reporting.describe_archive(r) for r in rows]}

    @app.post("/api/v1/exports/archive", status_code=202)
    def post_archive(p: Auth) -> dict[str, Any]:
        require(p, "request_deletion_or_archive")
        with session(p.tenant_id, engine) as s:
            return reporting.describe_archive(reporting.request_archive(s, p.tenant_id, p.user_id))

    @app.get("/api/v1/exports/archive/{export_id}/content")
    def get_archive_content(export_id: uuid.UUID, p: Auth) -> Response:
        require(p, "request_deletion_or_archive")
        with session(p.tenant_id, engine) as s:
            row = s.get(ArchiveExport, export_id)
            if row is None or not reporting.describe_archive(row)["downloadable"]:
                raise NotFoundError("archive")
            doc = s.get(DocumentRow, row.document_id)
            if doc is None or doc.deleted_at is not None:
                raise NotFoundError("archive")
            data = blobstore.get(p.tenant_id, doc.blob_key)
            write_audit(
                s,
                p.tenant_id,
                actor_type="user",
                actor_user_id=p.user_id,
                action="archive.downloaded",
                entity_type="archive_export",
                entity_id=row.id,
            )
            stamp = (row.finished_at or datetime.now(UTC)).strftime("%Y-%m-%d")
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="matchdesk-archive-{stamp}.zip"',
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    # ------------------------------------------------------------------ account deletion (S-16)
    def _deletion_body(s: Any, row: DeletionRequest | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return reporting.describe_deletion(row, views.user_names(s, [row.requested_by]))

    @app.get("/api/v1/account/deletion-request")
    def get_deletion(p: Auth) -> dict[str, Any]:
        require(p, "request_deletion_or_archive")
        with session(p.tenant_id, engine) as s:
            latest = s.scalar(select(DeletionRequest).order_by(DeletionRequest.created_at.desc()).limit(1))
            return {"request": _deletion_body(s, latest), "notice_days": reporting.DELETION_NOTICE.days}

    @app.post("/api/v1/account/deletion-requests", status_code=201)
    def post_deletion(body: DeletionBody, p: Auth) -> dict[str, Any]:
        require(p, "request_deletion_or_archive")
        with global_session(engine) as g:
            t = g.get(Tenant, p.tenant_id)
            name = t.name if t else ""
        if body.confirm_name.strip().casefold() != name.strip().casefold():
            raise HTTPException(422, "type the account name exactly to request its deletion")
        with session(p.tenant_id, engine) as s:
            row = reporting.request_deletion(s, p.tenant_id, p.user_id, body.reason)
            return {"request": _deletion_body(s, row)}

    @app.post("/api/v1/account/deletion-requests/{request_id}/cancel")
    def post_cancel_deletion(
        request_id: uuid.UUID,
        p: Auth,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        require(p, "request_deletion_or_archive")
        version = if_match(if_match_header)
        with session(p.tenant_id, engine) as s:
            row = s.get(DeletionRequest, request_id)
            if row is None:
                raise NotFoundError("deletion request")
            reporting.cancel_deletion(s, row, p.user_id, version)
            return {"request": _deletion_body(s, row)}

    # ------------------------------------------------------------------ operator S-18
    @app.get("/api/v1/operator/deletion-requests")
    def op_deletions(ctx: Ctx) -> dict[str, Any]:
        operator(ctx)
        rows = reporting.operator_deletions(engine)
        with global_session(engine) as g:
            names = dict(g.execute(select(Tenant.id, Tenant.name)).all())
        return {
            "items": [
                {**(reporting.describe_deletion(r) or {}), "tenant_name": names.get(r.tenant_id)}
                for r in sorted(rows, key=lambda r: r.created_at, reverse=True)
            ]
        }

    @app.post("/api/v1/operator/deletion-requests/{request_id}/decision")
    def op_decide_deletion(
        request_id: uuid.UUID,
        body: DeletionDecision,
        ctx: Ctx,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        operator(ctx)
        version = if_match(if_match_header)
        with operator_session(engine) as s:
            row = s.get(DeletionRequest, request_id)
            if row is None:
                raise NotFoundError("deletion request")
            row, after = reporting.decide_deletion(s, row, ctx.user_id, body.decision, body.note, version)
            tid, rid = row.tenant_id, row.id
            described = reporting.describe_deletion(row)
        with session(tid, engine) as s:  # the account's audit log records the operator's decision
            write_audit(
                s,
                tid,
                actor_type="operator",
                actor_user_id=ctx.user_id,
                action="deletion.scheduled" if body.decision == "schedule" else "deletion.declined",
                entity_type="deletion_request",
                entity_id=rid,
                before={"status": "requested"},
                after=after,
            )
        return {"request": described}


__all__ = ["register_b9_routes"]
