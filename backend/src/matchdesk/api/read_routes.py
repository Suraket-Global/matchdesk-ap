"""Read endpoints the web app's screens need and B3 did not build (B4). Wiring only.

- ``GET /vendors`` and ``GET /items``: the read copies from QuickBooks, for filters (S-08) and the
  alias form's "our item" search (S-11). Read rights as every other read copy (C K V).
- ``GET /audit-events`` and ``GET /audit-events/export``: the audit log of S-17 (TRD 12; C, and
  ``support_reader`` once support sessions exist). Insert-only table; there is no write route.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from sqlalchemy import Engine, Select, and_, or_, select

from matchdesk.api import views
from matchdesk.api.common import Auth, page_limit, require
from matchdesk.audit import AuditEvent
from matchdesk.qbo.models import Item, Vendor
from matchdesk.tenancy import session

EXPORT_MAX_ROWS = 50_000


def _event_body(e: AuditEvent, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "occurred_at": e.occurred_at.isoformat(),
        "actor_type": e.actor_type,
        "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
        "actor_name": names.get(e.actor_user_id) if e.actor_user_id else None,
        "action": e.action,
        "entity_type": e.entity_type,
        "entity_id": str(e.entity_id) if e.entity_id else None,
        "before": e.before,
        "after": e.after,
    }


def _cursor(value: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not value:
        return None
    try:
        at, ident = value.split("|", 1)
        return datetime.fromisoformat(at), uuid.UUID(ident)
    except ValueError:
        raise HTTPException(422, "cursor is not valid") from None


def _filtered(
    actor_user_id: uuid.UUID | None,
    action: str | None,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    since: datetime | None,
    until: datetime | None,
) -> Select[Any]:
    q = select(AuditEvent)
    if actor_user_id:
        q = q.where(AuditEvent.actor_user_id == actor_user_id)
    if action:
        q = q.where(AuditEvent.action.startswith(action))
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditEvent.entity_id == entity_id)
    if since:
        q = q.where(AuditEvent.occurred_at >= since)
    if until:
        q = q.where(AuditEvent.occurred_at < until)
    return q.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())


def _csv_cell(value: Any) -> str:
    """Formula-injection guard, as in the report CSV: a leading = + - @ is neutralised."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def register_read_routes(app: FastAPI, engine: Engine) -> None:
    @app.get("/api/v1/vendors")
    def list_vendors(p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            rows = s.scalars(select(Vendor).order_by(Vendor.name)).all()
            return {"items": [{"id": str(v.id), "name": v.name, "active": v.active} for v in rows]}

    @app.get("/api/v1/items")
    def list_items(p: Auth, q: str | None = None, limit: int | None = None) -> dict[str, Any]:
        require(p, "read")
        n = page_limit(limit)
        with session(p.tenant_id, engine) as s:
            query = select(Item).order_by(Item.sku, Item.name).limit(n)
            if q:
                like = f"%{q.strip()}%"
                query = query.where(or_(Item.sku.ilike(like), Item.name.ilike(like)))
            return {
                "items": [
                    {"id": str(i.id), "sku": i.sku, "name": i.name, "purchase_uom": i.purchase_uom}
                    for i in s.scalars(query).all()
                ]
            }

    @app.get("/api/v1/audit-events")
    def list_audit(
        p: Auth,
        cursor: str | None = None,
        limit: int | None = None,
        actor_user_id: uuid.UUID | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        require(p, "read_audit")
        n = page_limit(limit)
        after = _cursor(cursor)
        with session(p.tenant_id, engine) as s:
            q = _filtered(actor_user_id, action, entity_type, entity_id, since, until)
            if after is not None:
                at, ident = after
                q = q.where(
                    or_(
                        AuditEvent.occurred_at < at, and_(AuditEvent.occurred_at == at, AuditEvent.id < ident)
                    )
                )
            rows = list(s.scalars(q.limit(n + 1)).all())
            names = views.user_names(s, [e.actor_user_id for e in rows])
            last = rows[n - 1] if len(rows) > n else None
            return {
                "items": [_event_body(e, names) for e in rows[:n]],
                "next_cursor": f"{last.occurred_at.isoformat()}|{last.id}" if last else None,
            }

    @app.get("/api/v1/audit-events/export")
    def export_audit(
        p: Auth,
        actor_user_id: uuid.UUID | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Response:
        require(p, "read_audit")
        with session(p.tenant_id, engine) as s:
            q = _filtered(actor_user_id, action, entity_type, entity_id, since, until)
            rows = list(s.scalars(q.limit(EXPORT_MAX_ROWS)).all())
            names = views.user_names(s, [e.actor_user_id for e in rows])
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow(["occurred_at", "actor", "action", "entity_type", "entity_id", "before", "after"])
            for e in rows:
                body = _event_body(e, names)
                w.writerow(
                    [
                        _csv_cell(body["occurred_at"]),
                        _csv_cell(body["actor_name"] or body["actor_type"]),
                        _csv_cell(body["action"]),
                        _csv_cell(body["entity_type"]),
                        _csv_cell(body["entity_id"]),
                        _csv_cell(body["before"]),
                        _csv_cell(body["after"]),
                    ]
                )
            return Response(
                content=buf.getvalue(),
                media_type="text/csv",
                headers={
                    "Content-Disposition": 'attachment; filename="audit-log.csv"',
                    "X-Content-Type-Options": "nosniff",
                },
            )


__all__ = ["register_read_routes"]
