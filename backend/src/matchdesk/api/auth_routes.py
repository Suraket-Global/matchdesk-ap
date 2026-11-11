"""Sign-in, session, invitation and user-management routes (TRD 8.1, 12; B2). Wiring only."""

from __future__ import annotations

import ipaddress
import secrets
import uuid
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from matchdesk.api.common import BINDING_COOKIE, SESSION_COOKIE, Auth, Ctx, require
from matchdesk.core import Mailer, OutgoingMail, Settings, get_logger
from matchdesk.identity import (
    LINK_TTL,
    AuthError,
    IssuedSession,
    accept_invitation,
    create_invitation,
    describe_me,
    end_session,
    exchange_login_token,
    list_invitations,
    list_users,
    load_session,
    request_login_link,
    revoke_invitation,
    switch_tenant,
    update_membership,
)

log = get_logger("matchdesk.api.auth")

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
LINK_SENT = "If this address can sign in, a sign-in link is on its way. It expires in 10 minutes."
REFUSALS = {
    "invalid": (400, "This sign-in link is not valid any more. Ask for a new one."),
    "other_browser": (
        409,
        "This link was requested in another browser. Open it there, or ask for a new link from this browser.",
    ),
    "totp_required": (401, "Enter the current code from your authenticator app."),
    "rate_limited": (429, "Too many attempts. Wait a while and try again."),
}


class LinkRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)


class TokenExchange(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    totp_code: str | None = Field(default=None, max_length=10)


class InvitationAccept(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)
    role: str = Field(pattern="^(controller|clerk|viewer)$")


class ActiveTenant(BaseModel):
    tenant_id: uuid.UUID


class MembershipPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(controller|clerk|viewer)$")
    status: str | None = Field(default=None, pattern="^(active|deactivated)$")


def _ip(request: Request) -> str | None:
    """The peer address. Behind the proxy (TRD 7) this must become the proxy's forwarded address."""
    if request.client is None:
        return None
    try:
        return str(ipaddress.ip_address(request.client.host))
    except ValueError:
        return None


def _send(mailer: Mailer, mail: OutgoingMail) -> None:
    try:
        mailer.send(mail)
    except Exception as exc:  # the body and address are never logged
        log.error("mail_failed", extra={"reason": type(exc).__name__})


def set_session_cookie(response: Response, issued: IssuedSession) -> None:
    response.set_cookie(SESSION_COOKIE, issued.token, httponly=True, secure=True, samesite="lax", path="/")


def register_auth_routes(app: FastAPI, settings: Settings, engine: Engine, mailer: Mailer) -> None:
    def _session_body(issued: IssuedSession) -> dict[str, Any]:
        ctx = load_session(engine, issued.token, touch=False)
        assert ctx is not None
        return {**describe_me(engine, ctx), "csrf_token": issued.csrf_token}

    def _replace_session(request: Request, response: Response, issued: IssuedSession) -> None:
        # A new token at every sign-in; any session this browser already had ends (ASVS 7.2.4).
        old = request.cookies.get(SESSION_COOKIE)
        if old:
            ctx = load_session(engine, old, touch=False)
            if ctx is not None:
                end_session(engine, ctx.session_id)
        set_session_cookie(response, issued)

    @app.post("/api/v1/auth/login-links", status_code=202)
    def post_login_link(
        body: LinkRequest, request: Request, response: Response, background: BackgroundTasks
    ) -> dict[str, str]:
        binding = request.cookies.get(BINDING_COOKIE) or ""
        if not (40 <= len(binding) <= 64):
            binding = secrets.token_urlsafe(32)
        try:
            mail = request_login_link(engine, body.email, _ip(request), binding, settings)
        except AuthError as exc:
            raise HTTPException(*REFUSALS[exc.code]) from exc
        response.set_cookie(
            BINDING_COOKIE,
            binding,
            max_age=int(LINK_TTL.total_seconds()),
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        if mail is not None:
            background.add_task(_send, mailer, mail)
        return {"detail": LINK_SENT}

    @app.post("/api/v1/auth/sessions", status_code=201)
    def post_session(body: TokenExchange, request: Request, response: Response) -> dict[str, Any]:
        try:
            issued = exchange_login_token(
                engine,
                body.token,
                request.cookies.get(BINDING_COOKIE),
                _ip(request),
                body.totp_code,
                settings,
            )
        except AuthError as exc:
            raise HTTPException(*REFUSALS[exc.code]) from exc
        _replace_session(request, response, issued)
        response.delete_cookie(BINDING_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return _session_body(issued)

    @app.post("/api/v1/auth/session/extend")
    def post_extend(ctx: Ctx) -> dict[str, Any]:
        # The middleware already counted this request as activity; refused after the absolute limit.
        return {
            "idle_expires_at": ctx.idle_expires_at.isoformat(),
            "absolute_expires_at": ctx.absolute_expires_at.isoformat(),
        }

    @app.delete("/api/v1/auth/session", status_code=204)
    def delete_session(ctx: Ctx, response: Response) -> Response:
        end_session(engine, ctx.session_id)
        out = Response(status_code=204)
        out.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return out

    @app.get("/api/v1/me")
    def get_me(ctx: Ctx) -> dict[str, Any]:
        return describe_me(engine, ctx)

    @app.put("/api/v1/me/active-tenant")
    def put_active_tenant(body: ActiveTenant, ctx: Ctx, request: Request) -> dict[str, Any]:
        switch_tenant(engine, ctx, body.tenant_id)
        fresh = load_session(engine, request.cookies[SESSION_COOKIE], touch=False)
        assert fresh is not None
        return describe_me(engine, fresh)

    @app.post("/api/v1/invitations", status_code=201)
    def post_invitation(body: InvitationCreate, p: Auth, background: BackgroundTasks) -> dict[str, Any]:
        require(p, "manage_users")
        created, mail = create_invitation(engine, p, body.email, body.role, settings)
        background.add_task(_send, mailer, mail)
        return created

    @app.get("/api/v1/invitations")
    def get_invitations(p: Auth) -> dict[str, Any]:
        require(p, "manage_users")
        return {"items": list_invitations(engine, p)}

    @app.delete("/api/v1/invitations/{invitation_id}", status_code=204)
    def delete_invitation(invitation_id: uuid.UUID, p: Auth) -> Response:
        require(p, "manage_users")
        revoke_invitation(engine, p, invitation_id)
        return Response(status_code=204)

    @app.post("/api/v1/invitations/accept", status_code=201)
    def post_accept(body: InvitationAccept, request: Request, response: Response) -> dict[str, Any]:
        try:
            issued = accept_invitation(engine, body.token, _ip(request), settings)
        except AuthError as exc:
            status, _title = REFUSALS[exc.code]
            title = "This invitation is not valid any more." if exc.code == "invalid" else _title
            raise HTTPException(status, title) from exc
        _replace_session(request, response, issued)
        return _session_body(issued)

    @app.get("/api/v1/users")
    def get_users(p: Auth) -> dict[str, Any]:
        require(p, "manage_users")
        return {"items": list_users(engine, p)}

    @app.patch("/api/v1/memberships/{membership_id}")
    def patch_membership(membership_id: uuid.UUID, body: MembershipPatch, p: Auth) -> dict[str, Any]:
        require(p, "manage_users")
        return update_membership(engine, p, membership_id, body.role, body.status)


PUBLIC_API_PATHS = frozenset(
    {"/api/v1/auth/login-links", "/api/v1/auth/sessions", "/api/v1/invitations/accept"}
)

__all__ = ["PUBLIC_API_PATHS", "register_auth_routes", "set_session_cookie"]
