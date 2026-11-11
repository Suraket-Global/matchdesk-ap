"""Shared HTTP helpers: problem+json, cookie names, the signed-in principal (wiring only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from matchdesk.core import get_correlation_id
from matchdesk.identity import Principal, SessionContext
from matchdesk.tenancy import can

SESSION_COOKIE = "__Host-md_session"
BINDING_COOKIE = "__Host-md_signin"
CSRF_HEADER = "X-CSRF-Token"
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def problem(status: int, title: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": title,
            "correlation_id": get_correlation_id(),
        },
    )


def session_context(request: Request) -> SessionContext:
    ctx = getattr(request.state, "session", None)
    if ctx is None:
        raise HTTPException(401, "Not signed in")
    return ctx  # type: ignore[no-any-return]


def principal(request: Request) -> Principal:
    """The signed-in user in their active tenant. Without an active tenant, tenant data is 404."""
    p = session_context(request).principal()
    if p is None:
        raise HTTPException(404, "Not found")
    return p


def require(p: Principal, action: str) -> None:
    """The one permission check (schema.md 4.1 via ``tenancy.can``): 403 inside the own tenant."""
    if not can(p.role, action):
        raise HTTPException(403, "Forbidden")


Auth = Annotated[Principal, Depends(principal)]
Ctx = Annotated[SessionContext, Depends(session_context)]
