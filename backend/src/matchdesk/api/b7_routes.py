"""B7 routes (wiring only): pilot record (T-5.1.3), weekly summary S-14 (T-5.1.4), operator console
S-18 and support grants (T-5.1.5), email intake (T-3.3.4). TRD section 12 lists them."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select, text

from matchdesk import identity, intake, reporting
from matchdesk.api.common import Auth, Ctx, StaleVersion, if_match, require
from matchdesk.audit import write_audit
from matchdesk.core import ConflictError, Mailer, NotFoundError, Settings, get_logger
from matchdesk.identity.models import SupportGrant, Tenant
from matchdesk.intake.models import InboundMessage, IntakeSender, UploadBatch, UsageEvent
from matchdesk.reporting.models import BacktestReport, PilotEngagement
from matchdesk.tenancy import global_session, held_lock, operator_session, session

INBOUND_PATH = "/api/v1/inbound/email"
log = get_logger("matchdesk.api.operator")


class PilotBody(BaseModel):
    # B16: the fee in the account's currency; positive, at most two decimals (no default but CAD's).
    price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    period_start: date | None = None
    period_end: date | None = None
    refund_condition: str | None = Field(default=None, max_length=2000)
    refund_threshold: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    signed_terms_ref: str | None = Field(default=None, max_length=300)
    signed_by_name: str | None = Field(default=None, max_length=200)
    signed_by_role: str | None = Field(default=None, pattern="^(controller|owner)$")
    delivery_mode: str | None = Field(default=None, pattern="^(manual|application)$")
    payment_status: str | None = Field(default=None, pattern="^(unpaid|paid|refunded)$")
    outcome: str | None = Field(default=None, pattern="^(converted|refunded|ended)$")


EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    # B14 (acceptance M5): the account's first controller, invited as the account is created.
    controller_email: str | None = Field(default=None, min_length=3, max_length=254, pattern=EMAIL)


class ControllerInvite(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL)


class GrantRequest(BaseModel):
    hours: int = Field(ge=1, le=168)
    reason: str = Field(min_length=3, max_length=500)


class GrantDecision(BaseModel):
    decision: str = Field(pattern="^(grant|decline|end)$")


class SupportEnter(BaseModel):
    grant_id: uuid.UUID


class GoverningBody(BaseModel):
    report_id: uuid.UUID


class WeeklySend(BaseModel):
    week_start: date


class SenderBody(BaseModel):
    address_or_domain: str = Field(min_length=3, max_length=320)


class HeldDecision(BaseModel):
    decision: str = Field(pattern="^(release|discard)$")


def operator(ctx: Ctx) -> Ctx:
    if not ctx.is_operator:
        raise HTTPException(404, "Not found")  # the console does not exist for anyone else
    return ctx


def register_b7_routes(app: FastAPI, settings: Settings, engine: Engine, mailer: Mailer) -> None:
    # ------------------------------------------------------------------ pilot record (tenant side)
    @app.get("/api/v1/pilot")
    def get_pilot(p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            pilot = reporting.get_pilot(s, p.tenant_id)
            body: dict[str, Any] = {"pilot": reporting.describe_pilot(pilot) or None, "governing": None}
            if pilot is not None and pilot.governing_report_id:
                r = s.get(BacktestReport, pilot.governing_report_id)
                if r is not None:
                    body["governing"] = {
                        "report_id": str(r.id),
                        "period_start": r.period_start.isoformat(),
                        "period_end": r.period_end.isoformat(),
                        "version_no": r.version_no,
                    }
            return body

    @app.put("/api/v1/pilot/governing-report")
    def put_governing(body: GoverningBody, p: Auth) -> dict[str, Any]:
        require(p, "approve_report")
        with session(p.tenant_id, engine) as s:
            r = s.get(BacktestReport, body.report_id)
            if r is None:
                raise NotFoundError("report")
            pilot = reporting.set_governing(s, p.tenant_id, r, p.user_id)
            write_audit(
                s,
                p.tenant_id,
                actor_type="user",
                actor_user_id=p.user_id,
                action="pilot.governing_set",
                entity_type="pilot_engagement",
                entity_id=pilot.id,
                after={
                    "report_version": r.version_no,
                    "qualifying": str(pilot.refund_qualifying_amount),
                    "threshold": str(pilot.refund_threshold),
                    "currency": pilot.currency,  # B16: of the threshold and the qualifying total
                    "refund_due": pilot.refund_due,
                },
            )
            return reporting.describe_pilot(pilot)

    # ------------------------------------------------------------------ weekly summary S-14
    @app.get("/api/v1/weekly-summary")
    def get_weekly(p: Auth, week_start: date | None = None) -> dict[str, Any]:
        require(p, "read")
        week = reporting.week_of(week_start or datetime.now(UTC).date())
        with session(p.tenant_id, engine) as s:
            return {**reporting.summary(s, week), "sent": reporting.last_sent(s)}

    @app.post("/api/v1/weekly-summary/send")
    def post_weekly(body: WeeklySend, p: Auth) -> dict[str, Any]:
        require(p, "send_weekly_summary")
        # B10: recipients whose delivery failed or is pending are retried first; otherwise a new
        # manual run, once per week.
        # B14 (acceptance m1): one send at a time per account and week, so two presses never send
        # the same email twice; the second finds nothing left to send.
        with held_lock(engine, f"weekly_send:{p.tenant_id}:{reporting.week_of(body.week_start)}"):
            run = reporting.retry_week(engine, p.tenant_id, body.week_start, mailer, settings, p.user_id)
            if run is None:
                run = reporting.send_weekly(
                    engine, p.tenant_id, body.week_start, "manual", mailer, settings, p.user_id
                )
        if run is None:
            raise HTTPException(409, "The summary for this week was already sent by hand")
        return run

    # ------------------------------------------------------------------ support grants (S-16)
    @app.get("/api/v1/support-grants")
    def get_grants(p: Auth) -> dict[str, Any]:
        require(p, "manage_users")
        return {"items": identity.tenant_grants(engine, p.tenant_id)}

    @app.post("/api/v1/support-grants/{grant_id}/decision")
    def post_grant_decision(grant_id: uuid.UUID, body: GrantDecision, p: Auth) -> dict[str, Any]:
        require(p, "manage_users")
        with session(p.tenant_id, engine) as s:
            g = s.get(SupportGrant, grant_id)
            if g is None:
                raise NotFoundError("grant")
            g = identity.decide_grant(s, g, p.user_id, body.decision)
            return identity.describe_grant(g)

    # ------------------------------------------------------------------ operator console S-18
    def _tenant_rows(tenant_ids: list[uuid.UUID] | None = None) -> list[dict[str, Any]]:
        with global_session(engine) as g:
            q = select(Tenant).order_by(Tenant.created_at)
            if tenant_ids is not None:
                q = q.where(Tenant.id.in_(tenant_ids))
            tenants = list(g.scalars(q).all())
        now = datetime.now(UTC)
        with operator_session(engine) as s:
            pilots = {pe.tenant_id: pe for pe in s.scalars(select(PilotEngagement))}
            grants: dict[uuid.UUID, list[SupportGrant]] = {}
            for gr in s.scalars(select(SupportGrant)):
                grants.setdefault(gr.tenant_id, []).append(gr)
            units = dict(
                s.execute(select(UsageEvent.tenant_id, func.count()).group_by(UsageEvent.tenant_id)).all()
            )
            return [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "status": t.status,
                    "currency": t.currency,  # B16: the pilot fee is entered in it on S-18
                    "created_at": t.created_at.isoformat(),
                    "intake_address": intake.intake_address(t, settings),
                    "pilot": reporting.describe_pilot(pilots.get(t.id)) or None,
                    "usage_units": int(units.get(t.id, 0)),
                    "active_grant": any(identity.grant_is_active(g, now) for g in grants.get(t.id, [])),
                    "pending_requests": sum(1 for g in grants.get(t.id, []) if g.status == "requested"),
                }
                for t in tenants
            ]

    @app.get("/api/v1/operator/tenants")
    def op_tenants(ctx: Ctx) -> dict[str, Any]:
        operator(ctx)
        return {"items": _tenant_rows()}

    def _send_mail(mail: Any) -> None:
        try:
            mailer.send(mail)
        except Exception as exc:  # the body and address are never logged
            log.error("mail_failed", extra={"reason": type(exc).__name__})

    @app.post("/api/v1/operator/tenants", status_code=201)
    def op_create_tenant(body: TenantCreate, ctx: Ctx, background: BackgroundTasks) -> dict[str, Any]:
        operator(ctx)
        name = " ".join(body.name.split())
        with global_session(engine) as g:
            # B14 (acceptance M5, m1): one account per name. The lock makes two requests in the same
            # moment (a double press of the button) create one account; the second answers 409.
            g.execute(text("select pg_advisory_xact_lock(hashtext('operator:create_tenant'))"))
            if g.scalar(select(Tenant.id).where(func.lower(Tenant.name) == name.lower())) is not None:
                raise ConflictError(f'An account named "{name}" already exists. Open it from the list.')
            t = Tenant(name=name, status="pilot")
            g.add(t)
            g.flush()
            tid = t.id
        intake.ensure_intake_address(engine, tid, settings)
        if body.controller_email:
            _created, mail = identity.invite_first_controller(
                engine, ctx.user_id, tid, body.controller_email, settings
            )
            background.add_task(_send_mail, mail)
        return {**_tenant_rows([tid])[0], "first_controller": identity.first_controller_state(engine, tid)}

    @app.post("/api/v1/operator/tenants/{tenant_id}/controller-invitations", status_code=201)
    def op_invite_controller(
        tenant_id: uuid.UUID, body: ControllerInvite, ctx: Ctx, background: BackgroundTasks
    ) -> dict[str, Any]:
        """S-18: invite the account's first controller (B14, acceptance M5). Refused once the
        account has a controller, who then invites its users on S-16."""
        operator(ctx)
        _created, mail = identity.invite_first_controller(
            engine, ctx.user_id, tenant_id, body.email, settings
        )
        background.add_task(_send_mail, mail)
        return identity.first_controller_state(engine, tenant_id)

    @app.get("/api/v1/operator/tenants/{tenant_id}")
    def op_tenant(tenant_id: uuid.UUID, ctx: Ctx) -> dict[str, Any]:
        operator(ctx)
        rows = _tenant_rows([tenant_id])
        if not rows:
            raise NotFoundError("tenant")
        with operator_session(engine) as s:
            usage = reporting.usage_by_month(s, tenant_id)
        return {
            **rows[0],
            "usage": usage,
            "grants": identity.operator_grants(engine, tenant_id),
            # B14 (acceptance M5): whether the account can be signed in to yet.
            "first_controller": identity.first_controller_state(engine, tenant_id),
        }

    @app.put("/api/v1/operator/tenants/{tenant_id}/pilot")
    def op_put_pilot(
        tenant_id: uuid.UUID,
        body: PilotBody,
        ctx: Ctx,
        if_match_header: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        operator(ctx)
        with global_session(engine) as g:
            tenant = g.get(Tenant, tenant_id)
            if tenant is None:
                raise NotFoundError("tenant")
            currency = tenant.currency  # B16: the pilot record is always in the account's currency
        version = if_match(if_match_header) if if_match_header is not None else None
        values = body.model_dump(exclude_unset=True)
        try:
            with operator_session(engine) as s:
                pilot, before, after = reporting.save_pilot(s, tenant_id, values, version, currency)
                pid = pilot.id
        except reporting.PilotVersionConflict as exc:
            raise StaleVersion(exc.current) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        with session(tenant_id, engine) as s:  # the account's audit log records the operator's change
            write_audit(
                s,
                tenant_id,
                actor_type="operator",
                actor_user_id=ctx.user_id,
                action="pilot.created" if before is None else "pilot.updated",
                entity_type="pilot_engagement",
                entity_id=pid,
                before=before,
                after=after,
            )
        return after

    @app.post("/api/v1/operator/tenants/{tenant_id}/support-grants", status_code=201)
    def op_request_grant(tenant_id: uuid.UUID, body: GrantRequest, ctx: Ctx) -> dict[str, Any]:
        operator(ctx)
        try:
            return identity.request_grant(engine, ctx.user_id, tenant_id, body.hours, body.reason)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/v1/operator/support-session")
    def op_enter(body: SupportEnter, ctx: Ctx) -> dict[str, Any]:
        operator(ctx)
        g = identity.enter_support(engine, ctx.session_id, ctx.user_id, body.grant_id)
        return {"tenant_id": str(g.tenant_id), "ends_at": g.ends_at.isoformat() if g.ends_at else None}

    @app.delete("/api/v1/operator/support-session", status_code=204)
    def op_leave(ctx: Ctx) -> None:
        operator(ctx)
        identity.leave_support(engine, ctx.session_id)

    # ------------------------------------------------------------------ email intake
    @app.post(INBOUND_PATH, status_code=202)
    async def inbound(request: Request) -> dict[str, Any]:
        body = await request.body()
        try:
            intake.verify_signature(
                settings,
                body,
                request.headers.get("X-MatchDesk-Timestamp"),
                request.headers.get("X-MatchDesk-Signature"),
                datetime.now(UTC),
            )
            return await run_in_threadpool(intake.receive, engine, settings, body)
        except intake.InboundRefused as exc:
            raise HTTPException(exc.status, "Refused") from None

    @app.get("/api/v1/intake/email")
    def get_intake_email(p: Auth) -> dict[str, Any]:
        require(p, "read")
        with global_session(engine) as g:
            t = g.get(Tenant, p.tenant_id)
            address = intake.intake_address(t, settings) if t else None
        with session(p.tenant_id, engine) as s:
            senders = s.scalars(select(IntakeSender).order_by(IntakeSender.address_or_domain)).all()
            msgs = s.scalars(
                select(InboundMessage).order_by(InboundMessage.received_at.desc()).limit(100)
            ).all()
            # B14 (acceptance M3): what became of the attachments, so an accepted message with
            # nothing usable never reads as an invoice received.
            batches = {
                b.id: b
                for b in s.scalars(
                    select(UploadBatch).where(UploadBatch.id.in_([m.batch_id for m in msgs if m.batch_id]))
                )
            }
            return {
                "address": address,
                "provider": settings.inbound_provider,
                "senders": [{"id": str(x.id), "address_or_domain": x.address_or_domain} for x in senders],
                "messages": [
                    {
                        "id": str(m.id),
                        "from_address": m.from_address,
                        "subject": m.subject,
                        "attachment_count": m.attachment_count,
                        "received_at": m.received_at.isoformat(),
                        "status": m.status,
                        "batch_id": str(m.batch_id) if m.batch_id else None,
                        "files_read": batches[m.batch_id].file_count if m.batch_id in batches else None,
                        "files_refused": len(batches[m.batch_id].refused_files or [])
                        if m.batch_id in batches
                        else None,
                    }
                    for m in msgs
                ],
            }

    @app.post("/api/v1/intake/senders", status_code=201)
    def post_sender(body: SenderBody, p: Auth) -> dict[str, Any]:
        require(p, "edit_intake_settings")
        with session(p.tenant_id, engine) as s:
            try:
                row = intake.add_sender(s, p.tenant_id, body.address_or_domain, p.user_id)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return {"id": str(row.id), "address_or_domain": row.address_or_domain}

    @app.delete("/api/v1/intake/senders/{sender_id}", status_code=204)
    def delete_sender(sender_id: uuid.UUID, p: Auth) -> None:
        require(p, "edit_intake_settings")
        with session(p.tenant_id, engine) as s:
            try:
                intake.remove_sender(s, p.tenant_id, sender_id, p.user_id)
            except LookupError:
                raise NotFoundError("sender") from None

    @app.post("/api/v1/intake/messages/{message_id}/decision")
    def post_held(message_id: uuid.UUID, body: HeldDecision, p: Auth) -> dict[str, Any]:
        require(p, "release_held_email")
        try:
            m = intake.decide_held(engine, settings, p.tenant_id, message_id, p.user_id, body.decision)
        except LookupError:
            raise NotFoundError("message") from None
        return {"id": str(m.id), "status": m.status, "batch_id": str(m.batch_id) if m.batch_id else None}
