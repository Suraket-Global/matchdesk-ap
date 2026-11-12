"""Support access (T-5.1.5; schema.md 3.1, 4.1, 4.3; IT-29).

The operator asks for read-only access to one account, for 1 to 168 hours, with a reason. A
controller of that account grants it on S-16 (or declines), and can end it early. Only while a grant
is active may the operator who asked open the account as ``support_reader``: the session then
carries the tenant and the grant, every request re-checks the grant, and the role can read but never
change anything. Every step is in the account's audit log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ConflictError, NotFoundError
from matchdesk.identity.models import SessionRow, SupportGrant, Tenant, User
from matchdesk.tenancy import global_session, operator_session, session

MAX_HOURS = 168


def is_active(g: SupportGrant, at: datetime) -> bool:
    return (
        g.status == "active"
        and g.ended_early_at is None
        and g.starts_at is not None
        and g.ends_at is not None
        and g.starts_at <= at < g.ends_at
    )


def describe_grant(
    g: SupportGrant, names: dict[uuid.UUID, str] | None = None, at: datetime | None = None
) -> dict[str, Any]:
    now = at or datetime.now(UTC)
    status = g.status
    if status == "active" and not is_active(g, now):
        status = "ended"  # expired: shown as ended, never as active
    n = names or {}
    return {
        "id": str(g.id),
        "tenant_id": str(g.tenant_id),
        "status": status,
        "reason": g.reason,
        "hours_requested": g.hours_requested,
        "requested_by_name": n.get(g.requested_by),
        "requested_at": g.created_at.isoformat() if g.created_at else None,
        "granted_by_name": n.get(g.granted_by) if g.granted_by else None,
        "starts_at": g.starts_at.isoformat() if g.starts_at else None,
        "ends_at": g.ends_at.isoformat() if g.ends_at else None,
        "ended_early_at": g.ended_early_at.isoformat() if g.ended_early_at else None,
    }


def _names(engine: Engine, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    with global_session(engine) as s:
        return {u.id: u.display_name or u.email for u in s.scalars(select(User).where(User.id.in_(ids)))}


def request_grant(
    engine: Engine, operator_id: uuid.UUID, tenant_id: uuid.UUID, hours: int, reason: str
) -> dict[str, Any]:
    if not 1 <= hours <= MAX_HOURS:
        raise ValueError("support access lasts 1 to 168 hours")
    if not reason.strip():
        raise ValueError("a reason is required")
    with global_session(engine) as g:
        if g.get(Tenant, tenant_id) is None:
            raise NotFoundError("tenant")
    with operator_session(engine) as s:
        grant = SupportGrant(
            tenant_id=tenant_id, requested_by=operator_id, reason=reason.strip(), hours_requested=hours
        )
        s.add(grant)
        s.flush()
        body = describe_grant(grant)
    _audit(
        engine,
        tenant_id,
        "operator",
        operator_id,
        "support_grant.requested",
        uuid.UUID(body["id"]),
        {"hours": hours, "reason": reason.strip()},
    )
    return body


def _audit(
    engine: Engine,
    tenant_id: uuid.UUID,
    actor_type: str,
    actor: uuid.UUID,
    action: str,
    grant_id: uuid.UUID,
    after: dict[str, Any],
) -> None:
    # The audit row belongs to the account; the system writes it in the account's own transaction,
    # which reads nothing (the operator's own transaction never carries a tenant).
    with session(tenant_id, engine) as s:
        write_audit(
            s,
            tenant_id,
            actor_type=actor_type,
            actor_user_id=actor,
            action=action,
            entity_type="support_grant",
            entity_id=grant_id,
            after=after,
        )


def operator_grants(engine: Engine, tenant_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    with operator_session(engine) as s:
        q = select(SupportGrant).order_by(SupportGrant.created_at.desc())
        if tenant_id is not None:
            q = q.where(SupportGrant.tenant_id == tenant_id)
        rows = list(s.scalars(q).all())
    names = _names(engine, {r.requested_by for r in rows} | {r.granted_by for r in rows if r.granted_by})
    return [describe_grant(r, names) for r in rows]


def tenant_grants(engine: Engine, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    with session(tenant_id, engine) as s:
        rows = list(s.scalars(select(SupportGrant).order_by(SupportGrant.created_at.desc())).all())
    names = _names(engine, {r.requested_by for r in rows} | {r.granted_by for r in rows if r.granted_by})
    return [describe_grant(r, names) for r in rows]


def decide_grant(
    s: Session, grant: SupportGrant, user_id: uuid.UUID, decision: str, at: datetime | None = None
) -> SupportGrant:
    """``grant``, ``decline`` or ``end`` by a controller of the account (tenant session)."""
    now = at or datetime.now(UTC)
    if decision == "grant":
        if grant.status != "requested":
            raise ConflictError("only a request can be granted")
        grant.status, grant.granted_by = "active", user_id
        grant.starts_at, grant.ends_at = now, now + timedelta(hours=grant.hours_requested)
    elif decision == "decline":
        if grant.status != "requested":
            raise ConflictError("only a request can be declined")
        grant.status, grant.ended_by = "declined", user_id
    elif decision == "end":
        if grant.status != "active":
            raise ConflictError("only active access can be ended")
        grant.status, grant.ended_by = "ended", user_id
        if grant.ends_at is None or now < grant.ends_at:
            grant.ended_early_at = now
        # Any support session under this grant ends with it.
        s.execute(
            update(SessionRow)
            .where(SessionRow.support_grant_id == grant.id)
            .values(active_tenant_id=None, support_grant_id=None)
        )
    else:
        raise ValueError("unknown decision")
    s.flush()
    write_audit(
        s,
        grant.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action={
            "grant": "support_grant.granted",
            "decline": "support_grant.declined",
            "end": "support_grant.ended",
        }[decision],
        entity_type="support_grant",
        entity_id=grant.id,
        after={"status": grant.status, "ends_at": grant.ends_at.isoformat() if grant.ends_at else None},
    )
    return grant


def active_grant(
    engine: Engine, grant_id: uuid.UUID, operator_id: uuid.UUID, at: datetime | None = None
) -> SupportGrant | None:
    """The grant if it is active now and was asked for by this operator; else None."""
    now = at or datetime.now(UTC)
    with operator_session(engine) as s:
        g = s.get(SupportGrant, grant_id)
        if g is None or g.requested_by != operator_id or not is_active(g, now):
            return None
        s.expunge(g)
        return g


def enter_support(
    engine: Engine, session_id: uuid.UUID, operator_id: uuid.UUID, grant_id: uuid.UUID
) -> SupportGrant:
    g = active_grant(engine, grant_id, operator_id)
    if g is None:
        raise NotFoundError("support grant")
    with global_session(engine) as s:
        s.execute(
            update(SessionRow)
            .where(SessionRow.id == session_id)
            .values(active_tenant_id=g.tenant_id, support_grant_id=g.id)
        )
    _audit(
        engine,
        g.tenant_id,
        "operator",
        operator_id,
        "support_grant.entered",
        g.id,
        {"until": g.ends_at.isoformat() if g.ends_at else None},
    )
    return g


def leave_support(engine: Engine, session_id: uuid.UUID) -> None:
    with global_session(engine) as s:
        s.execute(
            update(SessionRow)
            .where(SessionRow.id == session_id)
            .values(active_tenant_id=None, support_grant_id=None)
        )
