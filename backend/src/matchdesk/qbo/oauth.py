"""QuickBooks connection: OAuth 2.0 authorisation-code flow, token sealing, refresh, disconnect
(T-3.1.1 (a) to (d); TRD 8.3; compliance/self-check.md section 6.4).

The real Intuit endpoints are selected by settings and left unconfigured (no developer account):
``IntuitTokenEndpoint`` refuses to run without a client id and secret. Tests and the local demo
use ``FakeIntuitTokenEndpoint``. Tokens are sealed with AES-256-GCM and a key id before they are
stored, never logged, and erased at disconnect. After a disconnect no sync and no match run may
use QuickBooks-derived rows; they carry a deletion date 30 days out.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ConflictError, NotFoundError, Settings, get_logger
from matchdesk.qbo.client import QboNotConfiguredError
from matchdesk.qbo.models import QboConnection, QboOauthState
from matchdesk.tenancy import seal, session, unseal

log = get_logger("matchdesk.qbo")
STATE_LIFETIME = timedelta(minutes=10)
RETENTION_AFTER_DISCONNECT = timedelta(days=30)


class RefreshExpiredError(RuntimeError):
    """The refresh token is no longer accepted: the tenant must reconnect."""


class TokenEndpoint(Protocol):
    def exchange(self, code: str, redirect_uri: str) -> dict[str, Any]: ...
    def refresh(self, refresh_token: str) -> dict[str, Any]: ...
    def revoke(self, token: str) -> None: ...


@dataclass
class FakeIntuitTokenEndpoint:
    """Fake authorisation server (IT-11). A code works once; ``expire_refresh`` makes refresh fail."""

    valid_codes: set[str] = field(default_factory=set)
    expire_refresh: bool = False
    revoked: list[str] = field(default_factory=list)

    def issue_code(self) -> str:
        code = secrets.token_urlsafe(16)
        self.valid_codes.add(code)
        return code

    def _tokens(self) -> dict[str, Any]:
        return {
            "access_token": "fake-access-" + secrets.token_urlsafe(12),
            "refresh_token": "fake-refresh-" + secrets.token_urlsafe(12),
            "expires_in": 3600,
            "x_refresh_token_expires_in": 8_726_400,
            "scope": "com.intuit.quickbooks.accounting",
        }

    def exchange(self, code: str, redirect_uri: str) -> dict[str, Any]:
        if code not in self.valid_codes:
            raise PermissionError("invalid_grant")
        self.valid_codes.discard(code)
        return self._tokens()

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        if self.expire_refresh:
            raise RefreshExpiredError("invalid_grant")
        return self._tokens()

    def revoke(self, token: str) -> None:
        self.revoked.append(hashlib.sha256(token.encode()).hexdigest()[:8])


class IntuitTokenEndpoint:
    """Intuit's token and revoke endpoints over HTTPS (URLs from settings, unverified until T-1.1.1)."""

    def __init__(self, settings: Settings) -> None:
        if not (settings.qbo_client_id and settings.qbo_client_secret and settings.qbo_redirect_uri):
            raise QboNotConfiguredError("Intuit OAuth client not configured (no developer account)")
        self.settings = settings

    def _post(self, url: str, form: dict[str, str]) -> dict[str, Any]:
        basic = base64.b64encode(
            f"{self.settings.qbo_client_id}:{self.settings.qbo_client_secret}".encode()
        ).decode()
        req = urllib.request.Request(  # noqa: S310 (https URL from settings)
            url,
            data=urllib.parse.urlencode(form).encode(),
            headers={"Authorization": f"Basic {basic}", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            body = resp.read()
        return json.loads(body) if body else {}

    def exchange(self, code: str, redirect_uri: str) -> dict[str, Any]:
        return self._post(
            self.settings.qbo_token_url,
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        )

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        return self._post(
            self.settings.qbo_token_url, {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    def revoke(self, token: str) -> None:
        self._post(self.settings.qbo_revoke_url, {"token": token})


def token_endpoint_from_settings(settings: Settings) -> TokenEndpoint:
    if settings.qbo_mode == "intuit":
        return IntuitTokenEndpoint(settings)
    return FakeIntuitTokenEndpoint()


def _hash(state: str) -> bytes:
    return hashlib.sha256(state.encode()).digest()


def _context(tenant_id: uuid.UUID) -> bytes:
    return b"qbo-token:" + str(tenant_id).encode()


def get_connection(s: Session) -> QboConnection | None:
    return s.scalar(select(QboConnection))


def processing_allowed(s: Session) -> bool:
    """False after a disconnect: no sync and no match run may use QuickBooks-derived rows
    (Intuit terms s. 12.2; self-check 6.4). A tenant that never connected is not blocked here,
    so documents can be checked against rows loaded another way (tests, the B1 fixtures)."""
    conn = get_connection(s)
    return conn is None or conn.status != "disconnected"


def start_authorization(
    s: Session, settings: Settings, tenant_id: uuid.UUID, user_id: uuid.UUID, session_id: uuid.UUID
) -> str:
    """Authorisation URL with a random single-use ``state`` bound to this session (T-3.1.1 (a))."""
    if settings.qbo_mode == "intuit" and not settings.qbo_client_id:
        raise QboNotConfiguredError("Intuit OAuth client not configured (no developer account)")
    state = secrets.token_urlsafe(32)
    s.add(
        QboOauthState(
            tenant_id=tenant_id,
            state_hash=_hash(state),
            session_id=session_id,
            user_id=user_id,
            expires_at=datetime.now(UTC) + STATE_LIFETIME,
        )
    )
    s.flush()
    query = urllib.parse.urlencode(
        {
            "client_id": settings.qbo_client_id or "unconfigured",
            "response_type": "code",
            "scope": settings.qbo_scopes,
            "redirect_uri": settings.qbo_redirect_uri or f"{settings.app_base_url}/oauth/intuit/callback",
            "state": state,
        }
    )
    return f"{settings.qbo_authorize_url}?{query}"


def complete_callback(
    s: Session,
    settings: Settings,
    endpoint: TokenEndpoint,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    state: str,
    code: str,
    realm_id: str,
    company_name: str | None = None,
) -> QboConnection:
    """Validate ``state`` (this tenant, this session, unused, unexpired), exchange the code and store
    sealed tokens (T-3.1.1 (b), (c)). A replayed or foreign state connects nothing."""
    pending = s.scalar(select(QboOauthState).where(QboOauthState.state_hash == _hash(state)))
    now = datetime.now(UTC)
    if pending is None or pending.session_id != session_id or pending.used_at is not None:
        raise NotFoundError("authorisation request")
    if pending.expires_at < now:
        raise NotFoundError("authorisation request")
    pending.used_at = now
    s.flush()
    tokens = endpoint.exchange(code, settings.qbo_redirect_uri)
    conn = get_connection(s)
    if conn is None:
        conn = QboConnection(
            tenant_id=tenant_id, realm_id=realm_id, token_key_id=settings.token_key_id, state_version=0
        )
        s.add(conn)
    elif conn.realm_id != realm_id:
        # The earlier company's purchase orders, bills and results are still held (until
        # ``delete_after`` once disconnected); mixing a second company into them would match one
        # company's invoices against the other's orders (B3/B4 review m1).
        raise ConflictError("this account is linked to a different QuickBooks company")
    conn.realm_id = realm_id
    conn.company_name = company_name
    conn.connected_by = pending.user_id
    conn.disconnected_at = None
    conn.delete_after = None
    _store_tokens(conn, settings, tenant_id, tokens)
    conn.status = "connected"
    conn.state_version += 1
    try:
        with s.begin_nested():
            s.flush()
    except IntegrityError:
        # The company is connected to another MatchDesk account (global unique realm). Refused with
        # the same words as any other refusal, never a 500 (m1).
        raise ConflictError("this QuickBooks company cannot be connected to this account") from None
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=pending.user_id,
        action="qbo.connected",
        entity_type="qbo_connection",
        entity_id=conn.id,
        after={"realm_id": realm_id, "scopes": conn.scopes_granted},
    )
    return conn


def _store_tokens(
    conn: QboConnection, settings: Settings, tenant_id: uuid.UUID, tokens: dict[str, Any]
) -> None:
    now = datetime.now(UTC)
    ctx = _context(tenant_id)
    conn.token_key_id = settings.token_key_id
    conn.refresh_token_enc = seal(
        settings.token_key, settings.token_key_id, tokens["refresh_token"].encode(), ctx
    )
    conn.access_token_enc = seal(
        settings.token_key, settings.token_key_id, tokens["access_token"].encode(), ctx
    )
    conn.access_expires_at = now + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    conn.refresh_expires_at = now + timedelta(seconds=int(tokens.get("x_refresh_token_expires_in", 0)))
    conn.scopes_granted = tokens.get("scope")


def access_token(s: Session, settings: Settings, endpoint: TokenEndpoint, tenant_id: uuid.UUID) -> str:
    """A valid access token, refreshing it when it has expired (T-3.1.1 (d)). A refused refresh
    marks the connection ``needs_reconnect`` (committed on its own) and raises ``ConflictError``.

    Only the Intuit reader needs a token, and that reader is not built until T-1.1.1: the recorded
    reader of B3 reads fixtures and never calls this, so no sync path refreshes tokens yet."""
    conn = get_connection(s)
    if conn is None or conn.status != "connected" or conn.refresh_token_enc is None:
        raise ConflictError("QuickBooks is not connected")
    keys = {settings.token_key_id: settings.token_key}
    ctx = _context(tenant_id)
    if conn.access_token_enc and conn.access_expires_at and conn.access_expires_at > datetime.now(UTC):
        return unseal(keys, conn.access_token_enc, ctx).decode()
    try:
        tokens = endpoint.refresh(unseal(keys, conn.refresh_token_enc, ctx).decode())
    except RefreshExpiredError:
        # Written in its own transaction: the caller's transaction is rolled back by the error, and
        # the connection must still say "needs reconnect" afterwards (B3/B4 review m2).
        engine = s.get_bind()
        with session(tenant_id, engine) as own:  # type: ignore[arg-type]
            row = own.get(QboConnection, conn.id, with_for_update=True)
            if row is not None and row.status == "connected":
                row.status = "needs_reconnect"
                row.state_version += 1
                own.flush()
                write_audit(
                    own,
                    tenant_id,
                    actor_type="system",
                    action="qbo.needs_reconnect",
                    entity_type="qbo_connection",
                    entity_id=row.id,
                )
        raise ConflictError("QuickBooks needs to be reconnected") from None
    _store_tokens(conn, settings, tenant_id, tokens)
    conn.state_version += 1
    s.flush()
    return str(tokens["access_token"])


def disconnect(
    s: Session, settings: Settings, endpoint: TokenEndpoint, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> QboConnection:
    """Revoke (best effort), erase tokens at once, stop processing, set the deletion date."""
    conn = get_connection(s)
    if conn is None:
        raise NotFoundError("QuickBooks connection")
    if conn.status == "disconnected":
        return conn
    if conn.refresh_token_enc is not None:
        try:
            endpoint.revoke(
                unseal(
                    {settings.token_key_id: settings.token_key}, conn.refresh_token_enc, _context(tenant_id)
                ).decode()
            )
        except Exception:  # revocation failure must not keep tokens or processing alive
            log.warning("qbo_revoke_failed", extra={"tenant_id": str(tenant_id)})
    now = datetime.now(UTC)
    conn.refresh_token_enc = None
    conn.access_token_enc = None
    conn.status = "disconnected"
    conn.disconnected_at = now
    conn.delete_after = now + RETENTION_AFTER_DISCONNECT
    conn.state_version += 1
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="qbo.disconnected",
        entity_type="qbo_connection",
        entity_id=conn.id,
        after={"delete_after": conn.delete_after.isoformat()},
    )
    return conn


def describe_connection(conn: QboConnection | None) -> dict[str, Any]:
    if conn is None:
        return {"status": "not_connected"}
    return {
        "status": conn.status,
        "company_name": conn.company_name,
        "realm_id": conn.realm_id,
        "scopes_granted": conn.scopes_granted,
        "last_success_at": conn.last_success_at.isoformat() if conn.last_success_at else None,
        "delete_after": conn.delete_after.isoformat() if conn.delete_after else None,
        "version": conn.state_version,
    }
