"""Shared HTTP helpers: problem+json, cookie names, the signed-in principal (wiring only)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from matchdesk.core import get_correlation_id
from matchdesk.identity import Principal, SessionContext
from matchdesk.tenancy import can
from matchdesk.tenancy.models import IdempotencyKey

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


def if_match(header: str | None) -> int:
    """``If-Match: <version>`` is required on updates of versioned records (TRD 12)."""
    if header is None:
        raise HTTPException(428, "If-Match with the record version is required")
    try:
        return int(header.strip().strip('"').removeprefix("W/").strip('"'))
    except ValueError:
        raise HTTPException(400, "If-Match must be the record version") from None


def conflict_response(current: dict[str, Any]) -> JSONResponse:
    """409 carrying the current record, so the client can show what changed (TRD 12, IT-14)."""
    body = {
        "type": "about:blank",
        "title": "The record changed",
        "status": 409,
        "detail": "The record changed since you loaded it",
        "correlation_id": get_correlation_id(),
        "current": current,
    }
    return JSONResponse(status_code=409, media_type="application/problem+json", content=body)


class StaleVersion(Exception):
    """Raised by an endpoint body when ``If-Match`` does not equal the stored version."""

    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("stale version")
        self.current = current


def page_limit(limit: int | None) -> int:
    if limit is None:
        return 50
    if limit < 1 or limit > 200:
        raise HTTPException(422, "limit must be between 1 and 200")
    return limit


def idempotent_replay(
    s: Any, p: Principal, key: str | None, request_hash: bytes
) -> tuple[str, uuid.UUID] | None:
    """The stored (entity type, id) of an earlier request with this key, or None (TRD 6.3)."""
    if not key:
        return None
    seen = s.scalar(
        select(IdempotencyKey).where(IdempotencyKey.user_id == p.user_id, IdempotencyKey.key == key)
    )
    if seen is None:
        return None
    if seen.expires_at < datetime.now(UTC):
        s.delete(seen)
        s.flush()
        return None
    if seen.request_hash != request_hash:
        raise HTTPException(409, "Idempotency key reused with a different request")
    if seen.result_entity_id is None:
        return None
    return str(seen.result_entity_type), seen.result_entity_id


def remember(
    s: Any,
    p: Principal,
    key: str | None,
    request_hash: bytes,
    status: int,
    entity_type: str,
    entity_id: uuid.UUID,
) -> None:
    if not key:
        return
    s.add(
        IdempotencyKey(
            tenant_id=p.tenant_id,
            user_id=p.user_id,
            key=key,
            request_hash=request_hash,
            response_status=status,
            result_entity_type=entity_type,
            result_entity_id=entity_id,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    s.flush()


def body_hash(value: Any) -> bytes:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).digest()


def money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
