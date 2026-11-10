"""Sessions and memberships (B1 subset). Sign-in links, invitations and TOTP are T-2.2.3, not built."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select

from matchdesk.identity.models import Membership, SessionRow, Tenant, User
from matchdesk.tenancy import global_session, session

SESSION_LIFETIME = timedelta(hours=24)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def issue_session(engine: Engine, user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """Create a session and return the raw token (only its hash is stored)."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with global_session(engine) as s:
        s.add(
            SessionRow(
                user_id=user_id,
                token_hash=hash_token(token),
                active_tenant_id=tenant_id,
                last_seen_at=now,
                expires_at=now + SESSION_LIFETIME,
            )
        )
    return token


def resolve_session(engine: Engine, token: str) -> Principal | None:
    now = datetime.now(UTC)
    with global_session(engine) as s:
        row = s.scalar(select(SessionRow).where(SessionRow.token_hash == hash_token(token)))
        if row is None or row.ended_at is not None or row.expires_at < now or row.active_tenant_id is None:
            return None
        user_id, tenant_id = row.user_id, row.active_tenant_id
    with session(tenant_id, engine) as s:
        m = s.scalar(select(Membership).where(Membership.user_id == user_id, Membership.status == "active"))
        if m is None:
            return None
        return Principal(user_id=user_id, tenant_id=tenant_id, role=m.role)


__all__ = [
    "Membership",
    "Principal",
    "SessionRow",
    "Tenant",
    "User",
    "hash_token",
    "issue_session",
    "resolve_session",
]
