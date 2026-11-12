"""Email intake (T-3.3.4; schema.md inbound_messages, intake_senders; IT-12).

Each account has an intake address ``<local part>@<intake domain>``. The provider posts every
message to ``POST /api/v1/inbound/email``; the request must be signed (``verify_signature``) or it is
refused before anything is read. A message from an allowed sender (an exact address, or a whole
domain written as ``@example.invalid``) has its PDF, PNG and JPEG attachments put into a new intake
batch, exactly as if a person had uploaded them. A message from anyone else is held for a person on
S-06, who releases it (then the same happens) or discards it. A message is handled once whatever the
provider retries (unique message id). The raw message is kept 7 days (schema.md section 8).

The provider is chosen by settings: ``local`` (HMAC-SHA256 over ``<timestamp>.<body>`` with the
server's inbound signing key; ``make demo-email``) is the only one built; a hosted provider needs its
account and refuses.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from matchdesk import blobstore
from matchdesk.audit import write_audit
from matchdesk.core import ConflictError, Settings, get_logger
from matchdesk.identity.models import Tenant
from matchdesk.intake.models import DocumentRow, InboundMessage, IntakeSender
from matchdesk.intake.service import add_file, create_batch
from matchdesk.tenancy import global_session, session

log = get_logger("matchdesk.intake.email")

MAX_SKEW = timedelta(minutes=5)
RAW_RETENTION = timedelta(days=7)
ACCEPTED = {b"%PDF-": "application/pdf", b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DOMAIN = re.compile(r"^@?[a-z0-9.-]+\.[a-z]{2,}$", re.I)


class InboundRefused(Exception):
    """Signature, provider or recipient refused: answered with 401 or 404, nothing stored."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status


def signing_key(settings: Settings) -> bytes:
    """The configured key; in dev and test, without one, a key derived from the session key so the
    local demo works with no extra secret. Never a constant."""
    if settings.inbound_signing_key:
        return settings.inbound_signing_key.encode()
    if settings.env in ("dev", "test") and settings.session_key:
        return hmac.new(settings.session_key.encode(), b"matchdesk inbound email", hashlib.sha256).digest()
    raise InboundRefused(503, "email intake is not configured")


def sign(body: bytes, timestamp: str, key: bytes) -> str:
    return hmac.new(key, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify_signature(
    settings: Settings, body: bytes, timestamp: str | None, signature: str | None, now: datetime
) -> None:
    if settings.inbound_provider != "local":
        # A hosted provider (Postmark, Mailgun, SES) has its own signature scheme and needs its account.
        raise InboundRefused(503, f"inbound provider {settings.inbound_provider} is not configured")
    if not timestamp or not signature:
        raise InboundRefused(401, "unsigned")
    try:
        at = datetime.fromtimestamp(int(timestamp), UTC)
    except (ValueError, OverflowError):
        raise InboundRefused(401, "bad timestamp") from None
    if abs(now - at) > MAX_SKEW:
        raise InboundRefused(401, "stale")
    if not hmac.compare_digest(sign(body, timestamp, signing_key(settings)), signature.strip().lower()):
        raise InboundRefused(401, "bad signature")


def intake_address(tenant: Tenant, settings: Settings) -> str | None:
    return f"{tenant.intake_address_local}@{settings.intake_domain}" if tenant.intake_address_local else None


def ensure_intake_address(engine: Engine, tenant_id: uuid.UUID, settings: Settings) -> str:
    with global_session(engine) as s:
        t = s.get(Tenant, tenant_id)
        if t is None:
            raise ValueError("tenant")
        if not t.intake_address_local:
            t.intake_address_local = f"invoices-{secrets.token_hex(4)}"
        return intake_address(t, settings) or ""


def _tenant_for(engine: Engine, to: str, settings: Settings) -> uuid.UUID:
    local, _, domain = to.strip().lower().rpartition("@")
    if not local or domain != settings.intake_domain.lower():
        raise InboundRefused(404, "unknown recipient")
    with global_session(engine) as s:
        tid = s.scalar(
            select(Tenant.id).where(Tenant.intake_address_local == local, Tenant.status != "ended")
        )
    if tid is None:
        raise InboundRefused(404, "unknown recipient")
    return tid


def sender_allowed(s: Session, address: str) -> bool:
    addr = address.strip().lower()
    domain = "@" + addr.rpartition("@")[2]
    allowed = {a.lower() for a in s.scalars(select(IntakeSender.address_or_domain))}
    return addr in allowed or domain in allowed


def _attachments(payload: dict[str, Any]) -> list[tuple[str, bytes, str]]:
    out: list[tuple[str, bytes, str]] = []
    for a in payload.get("attachments") or []:
        try:
            data = base64.b64decode(a.get("content_base64") or "", validate=True)
        except (ValueError, TypeError):
            continue
        mime = next((m for sig, m in ACCEPTED.items() if data.startswith(sig)), None)
        if mime is None or len(data) > MAX_ATTACHMENT_BYTES:
            continue  # the declared type and name are ignored (TRD 8.7)
        out.append((str(a.get("filename") or "attachment")[:255], data, mime))
    return out


def _process(s: Session, tenant_id: uuid.UUID, msg: InboundMessage, payload: dict[str, Any]) -> None:
    files = _attachments(payload)
    batch = create_batch(s, tenant_id, source="email")
    for n, (name, data, mime) in enumerate(files):
        add_file(
            s,
            tenant_id,
            None,
            batch.id,
            f"email:{msg.provider_message_id}:{n}",
            data,
            mime,
            name,
            source="email",
        )
    msg.batch_id = batch.id
    msg.status = "processed"


def receive(engine: Engine, settings: Settings, body: bytes, now: datetime | None = None) -> dict[str, Any]:
    """Handle one verified message. Idempotent on the provider's message id."""
    at = now or datetime.now(UTC)
    try:
        payload = json.loads(body)
        message_id = str(payload["message_id"])[:500]
        sender = str(payload["from"]).strip()[:320]
        to = str(payload["to"]).strip()[:320]
    except (ValueError, KeyError, TypeError):
        raise InboundRefused(422, "not a message") from None
    if not ADDRESS.match(sender):
        raise InboundRefused(422, "no sender")
    tenant_id = _tenant_for(engine, to, settings)
    with session(tenant_id, engine) as s:
        seen = s.scalar(select(InboundMessage).where(InboundMessage.provider_message_id == message_id))
        if seen is not None:
            return {"status": seen.status, "duplicate": True}
        raw_id = uuid.uuid4()
        key = blobstore.build_key(
            tenant_id, "inbound_raw", body, source="email", record_id=raw_id, ext="json"
        )
        blobstore.put(tenant_id, key, body, content_type="application/json", settings=settings)
        s.add(
            DocumentRow(
                id=raw_id,
                tenant_id=tenant_id,
                purpose="inbound_raw",
                source="email",
                blob_key=key,
                sha256=hashlib.sha256(body).digest(),
                mime_type="application/json",
                byte_size=len(body),
                state="succeeded",
                correlation_id=uuid.uuid4(),
            )
        )
        s.flush()
        msg = InboundMessage(
            tenant_id=tenant_id,
            provider_message_id=message_id,
            from_address=sender,
            subject=(str(payload.get("subject") or "")[:300] or None),
            attachment_count=len(payload.get("attachments") or []),
            received_at=at,
            status="held",
            raw_document_id=raw_id,
        )
        s.add(msg)
        s.flush()
        if sender_allowed(s, sender):
            _process(s, tenant_id, msg, payload)
        s.flush()
        write_audit(
            s,
            tenant_id,
            actor_type="system",
            action="intake_email.processed" if msg.status == "processed" else "intake_email.held",
            entity_type="inbound_message",
            entity_id=msg.id,
            after={"status": msg.status, "attachments": msg.attachment_count},
        )
        log.info("inbound_email", extra={"status": msg.status})  # no address, subject or content
        return {
            "status": msg.status,
            "duplicate": False,
            "batch_id": str(msg.batch_id) if msg.batch_id else None,
        }


def decide_held(
    engine: Engine,
    settings: Settings,
    tenant_id: uuid.UUID,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    decision: str,
) -> InboundMessage:
    """``release`` (attachments into a batch) or ``discard`` a held message."""
    with session(tenant_id, engine) as s:
        msg = s.get(InboundMessage, message_id)
        if msg is None:
            raise LookupError("message")
        if msg.status != "held":
            raise ConflictError("this message was already decided")
        if decision == "release":
            raw = s.get(DocumentRow, msg.raw_document_id) if msg.raw_document_id else None
            if raw is None or raw.deleted_at is not None:
                raise ConflictError("the message is older than 7 days and was deleted")
            payload = json.loads(blobstore.get(tenant_id, raw.blob_key, settings=settings))
            _process(s, tenant_id, msg, payload)
        elif decision == "discard":
            msg.status = "discarded"
        else:
            raise ValueError("unknown decision")
        msg.decided_by, msg.decided_at = user_id, datetime.now(UTC)
        s.flush()
        write_audit(
            s,
            tenant_id,
            actor_type="user",
            actor_user_id=user_id,
            action="intake_email.released" if decision == "release" else "intake_email.discarded",
            entity_type="inbound_message",
            entity_id=msg.id,
            before={"status": "held"},
            after={"status": msg.status},
        )
        s.expunge(msg)
        return msg


def add_sender(s: Session, tenant_id: uuid.UUID, value: str, user_id: uuid.UUID) -> IntakeSender:
    v = value.strip().lower()
    if not (ADDRESS.match(v) or DOMAIN.match(v)):
        raise ValueError("enter an email address or a domain such as @supplier.example")
    if DOMAIN.match(v) and not v.startswith("@") and "@" not in v:
        v = "@" + v
    if s.scalar(select(IntakeSender).where(IntakeSender.address_or_domain == v)) is not None:
        raise ConflictError("already allowed")
    row = IntakeSender(tenant_id=tenant_id, address_or_domain=v, added_by=user_id)
    s.add(row)
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="intake_sender.added",
        entity_type="intake_sender",
        entity_id=row.id,
        after={"sender": v},
    )
    return row


def remove_sender(s: Session, tenant_id: uuid.UUID, sender_id: uuid.UUID, user_id: uuid.UUID) -> None:
    row = s.get(IntakeSender, sender_id)
    if row is None:
        raise LookupError("sender")
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="intake_sender.removed",
        entity_type="intake_sender",
        entity_id=row.id,
        before={"sender": row.address_or_domain},
    )
    s.delete(row)
    s.flush()


def purge_raw(engine: Engine, settings: Settings, now: datetime | None = None) -> int:
    """Delete raw inbound messages older than 7 days (schema.md section 8). Worker housekeeping."""
    cutoff = (now or datetime.now(UTC)) - RAW_RETENTION
    with global_session(engine) as g:
        tenants = list(g.scalars(select(Tenant.id)).all())
    n = 0
    for tid in tenants:
        with session(tid, engine) as s:
            for doc in s.scalars(
                select(DocumentRow).where(
                    DocumentRow.purpose == "inbound_raw",
                    DocumentRow.deleted_at.is_(None),
                    DocumentRow.created_at < cutoff,
                )
            ):
                blobstore.delete(tid, doc.blob_key, settings=settings)
                doc.deleted_at = datetime.now(UTC)
                n += 1
    return n
