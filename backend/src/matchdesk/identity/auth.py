"""Sign-in links, sessions, anti-forgery tokens, invitations, memberships (TRD 8.1; T-2.2.3; B2).

Every token (sign-in link, invitation, session) is 256 random bits from ``secrets``; only its
SHA-256 hash is stored. Raw tokens are returned to the caller once and never logged. Functions
that send mail return the message instead of sending it, so the API can answer first and send
afterwards: the response to a sign-in request is the same, and as fast, for unknown addresses.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    OutgoingMail,
    Settings,
    load_settings,
)
from matchdesk.identity import totp
from matchdesk.identity.models import (
    ROLES,
    AuthRateEvent,
    Invitation,
    LoginToken,
    Membership,
    SessionRow,
    Tenant,
    User,
)
from matchdesk.identity.secrets_box import seal, unseal
from matchdesk.tenancy import global_session, invitation_lookup_session, session, user_session

LINK_TTL = timedelta(minutes=10)
INVITE_TTL = timedelta(days=7)
IDLE_TIMEOUT = timedelta(minutes=60)
ABSOLUTE_LIFETIME = timedelta(hours=24)
# kind -> (limit, window). TRD 8.1: 5 links per address per 15 minutes; 20 per IP per hour;
# 10 failed token exchanges per IP per hour.
RATE_LIMITS: dict[str, tuple[int, timedelta]] = {
    "link_address": (5, timedelta(minutes=15)),
    "link_ip": (20, timedelta(hours=1)),
    "exchange_fail_ip": (10, timedelta(hours=1)),
    # B2-S02: wrong one-time codes per account, whatever the IP. Reaching it burns every open link.
    "totp_fail_user": (5, timedelta(minutes=15)),
}
# B2-S02: a link is burned after this many wrong one-time codes.
LINK_MAX_TOTP_FAILURES = 3
# B2-S07: a sign-in link request takes at least this long, so known and unknown addresses look alike.
LINK_REQUEST_FLOOR_NS = 40_000_000
TOTP_CONTEXT = b"matchdesk:users.totp_secret_enc"


class AuthError(Exception):
    """Sign-in refused. ``code`` is for the API; the public message never says which check failed
    except where the user must act differently (another browser, operator code)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    session_id: uuid.UUID | None = None


@dataclass(frozen=True)
class SessionContext:
    session_id: uuid.UUID
    user_id: uuid.UUID
    is_operator: bool
    tenant_id: uuid.UUID | None
    role: str | None
    csrf_token_hash: bytes
    idle_expires_at: datetime
    absolute_expires_at: datetime

    def principal(self) -> Principal | None:
        if self.is_operator or self.tenant_id is None or self.role is None:
            return None
        return Principal(self.user_id, self.tenant_id, self.role, self.session_id)


@dataclass(frozen=True)
class IssuedSession:
    token: str
    csrf_token: str
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def csrf_for(token: str, settings: Settings | None = None) -> str:
    """The session's anti-forgery token: HMAC of the session token under the session key."""
    key = (settings or load_settings()).session_key
    if not key:
        raise RuntimeError("MATCHDESK_SESSION_KEY is not set")
    mac = hmac.new(key.encode(), b"csrf\x00" + token.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def csrf_matches(ctx: SessionContext, presented: str | None) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(hash_token(presented), ctx.csrf_token_hash)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _rate_key(cfg: Settings, kind: str, value: str) -> bytes:
    """HMAC under the server's session key (B2-S06): the address or IP cannot be recovered by
    hashing candidates, because the key never leaves the server."""
    if not cfg.session_key:
        raise RuntimeError("MATCHDESK_SESSION_KEY is not set")
    msg = f"rate\x00{kind}\x00{value.strip().lower()}".encode()
    return hmac.new(cfg.session_key.encode(), msg, hashlib.sha256).digest()


def _lock_key(s: Session, key_hash: bytes) -> None:
    """Serialise every counter on one key for the rest of the transaction (B2-S04)."""
    s.execute(
        text("select pg_advisory_xact_lock(:k)"),
        {"k": int.from_bytes(key_hash[:8], "big", signed=True)},
    )


def _over_limit(s: Session, cfg: Settings, kind: str, value: str, now: datetime) -> bool:
    limit, window = RATE_LIMITS[kind]
    key = _rate_key(cfg, kind, value)
    _lock_key(s, key)
    n = s.scalar(
        select(func.count())
        .select_from(AuthRateEvent)
        .where(
            AuthRateEvent.kind == kind,
            AuthRateEvent.key_hash == key,
            AuthRateEvent.created_at > now - window,
        )
    )
    return int(n or 0) >= limit


def _count_event(s: Session, cfg: Settings, kind: str, value: str, now: datetime) -> None:
    s.add(AuthRateEvent(kind=kind, key_hash=_rate_key(cfg, kind, value), created_at=now))


def _take(s: Session, cfg: Settings, kind: str, value: str, now: datetime) -> bool:
    """Count one event if the limit allows it, in one statement under the key's lock (B2-S04).
    Returns False, counting nothing, when the limit is reached."""
    limit, window = RATE_LIMITS[kind]
    key = _rate_key(cfg, kind, value)
    _lock_key(s, key)
    taken = s.execute(
        text(
            "insert into auth_rate_events (kind, key_hash, created_at) "
            "select :kind, :key, :now where (select count(*) from auth_rate_events "
            "where kind = :kind and key_hash = :key and created_at > :since) < :limit returning id"
        ),
        {"kind": kind, "key": key, "now": now, "since": now - window, "limit": limit},
    ).first()
    return taken is not None


def _pad(started_ns: int) -> None:
    remaining = LINK_REQUEST_FLOOR_NS - (time.perf_counter_ns() - started_ns)
    if remaining > 0:
        time.sleep(remaining / 1_000_000_000)


def _active_memberships(engine: Engine, user_id: uuid.UUID) -> list[tuple[uuid.UUID, str, str]]:
    """(tenant_id, role, tenant name) for every active membership in a tenant that has not ended."""
    with user_session(user_id, engine) as s:
        rows = s.execute(
            select(Membership.tenant_id, Membership.role, Tenant.name)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.user_id == user_id,
                Membership.status == "active",
                Tenant.status != "ended",
            )
            .order_by(Membership.created_at, Membership.tenant_id)
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]


# ---------------------------------------------------------------- sign-in links


def request_login_link(
    engine: Engine,
    email: str,
    ip: str | None,
    browser_binding: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> OutgoingMail | None:
    """Prepare a sign-in link for a known, active address. Returns the message to send, or None.

    The caller answers identically either way. Raises ``AuthError('rate_limited')`` only for the
    per-IP limit, which says nothing about the address; the per-address limit is silent.
    """
    started = time.perf_counter_ns()
    try:
        return _request_login_link(engine, email, ip, browser_binding, settings or load_settings(), _now(now))
    finally:
        _pad(started)  # B2-S07: the same floor for known, unknown and refused addresses


def check_link_ip(engine: Engine, ip: str | None, settings: Settings | None = None) -> None:
    """Count one link request against the IP; ``AuthError('rate_limited')`` over the limit."""
    if not ip:
        return
    cfg = settings or load_settings()
    with global_session(engine) as s:
        if not _take(s, cfg, "link_ip", ip, _now(None)):
            raise AuthError("rate_limited")


def _request_login_link(
    engine: Engine, email: str, ip: str | None, browser_binding: str, cfg: Settings, at: datetime
) -> OutgoingMail | None:
    address = email.strip()
    token = new_token()
    with global_session(engine) as s:
        if ip and not _take(s, cfg, "link_ip", ip, at):
            raise AuthError("rate_limited")
        if not _take(s, cfg, "link_address", address, at):
            return None
        user = s.scalar(select(User).where(User.email == address, User.deactivated_at.is_(None)))
        user_id = user.id if user is not None else None
        is_operator = bool(user and user.is_operator)
    # The membership query runs for unknown addresses too, against an identifier nobody has.
    memberships = _active_memberships(engine, user_id or uuid.uuid4())
    if user_id is None or (not is_operator and not memberships):
        return None
    with global_session(engine) as s:
        # requested_ip is no longer stored (B2-S06); the column stays null until it is dropped.
        s.add(
            LoginToken(
                user_id=user_id,
                token_hash=hash_token(token),
                browser_binding_hash=hash_token(browser_binding),
                expires_at=at + LINK_TTL,
                created_at=at,
            )
        )
    link = f"{cfg.app_base_url}/login/verify#t={token}"
    return OutgoingMail(
        to=address,
        subject="Your MatchDesk sign-in link",
        body=(
            "Open this link in the same browser where you asked for it, then press Sign in.\n\n"
            f"{link}\n\nThe link works once and expires in 10 minutes. "
            "If you did not ask for it, ignore this message.\n"
        ),
    )


def exchange_login_token(
    engine: Engine,
    token: str,
    browser_binding: str | None,
    ip: str | None,
    totp_code: str | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> IssuedSession:
    """Consume a sign-in link (POST only) and start a new session. Refusals count against the IP."""
    cfg = settings or load_settings()
    at = _now(now)
    refusal: str | None = None
    user_id: uuid.UUID | None = None
    with global_session(engine) as s:
        if ip and _over_limit(s, cfg, "exchange_fail_ip", ip, at):
            raise AuthError("rate_limited")
        row = s.scalar(select(LoginToken).where(LoginToken.token_hash == hash_token(token)).with_for_update())
        # The user row is locked too: one-time-code checks and counters for one account run one at
        # a time, so a step is used once and failures are counted exactly (B2-S02, B2-S04).
        user = s.get(User, row.user_id, with_for_update=True) if row is not None else None
        if row is None or row.used_at is not None or row.expires_at <= at or user is None:
            refusal = "invalid"
        elif user.deactivated_at is not None:
            refusal = "invalid"
        elif not browser_binding or not hmac.compare_digest(
            hash_token(browser_binding), row.browser_binding_hash
        ):
            refusal = "other_browser"  # not consumed: the right browser can still use it
        elif user.is_operator:
            refusal = _operator_factor(s, cfg, user, totp_code, at, row)
        if refusal is None and row is not None and user is not None:
            row.used_at = at
            user_id = user.id
        elif ip:
            _count_event(s, cfg, "exchange_fail_ip", ip, at)
    if refusal is not None or user_id is None:
        raise AuthError(refusal or "invalid")
    memberships = _active_memberships(engine, user_id)
    tenant_id = memberships[0][0] if memberships else None
    issued = _issue(engine, user_id, tenant_id, cfg, at)
    if tenant_id is not None:
        with session(tenant_id, engine) as s:
            write_audit(
                s,
                tenant_id,
                actor_type="user",
                actor_user_id=user_id,
                action="sign_in",
                entity_type="user",
                entity_id=user_id,
            )
    return issued


def _check_totp(cfg: Settings, user: User, code: str | None, at: datetime) -> int | None:
    if not code or user.totp_secret_enc is None:
        return None
    secret = unseal({cfg.token_key_id: cfg.token_key}, user.totp_secret_enc, TOTP_CONTEXT)
    return totp.verify(secret, code.strip(), at, user.totp_last_step)


def _operator_factor(
    s: Session, cfg: Settings, user: User, code: str | None, at: datetime, link: LoginToken | None
) -> str | None:
    """Check an operator's one-time code with the user row locked by the caller. Returns a refusal
    code or None. Wrong codes count per account and per link; at the account limit every open link
    is burned and further attempts are refused for the window (B2-S02). A step is stored as used in
    the same transaction (B2-S04)."""
    if _over_limit(s, cfg, "totp_fail_user", str(user.id), at):
        _burn_links(s, user.id, at)
        return "rate_limited"
    if not code:
        return "totp_required"  # nothing guessed: not counted
    step = _check_totp(cfg, user, code, at)
    if step is not None:
        user.totp_last_step = step
        return None
    _count_event(s, cfg, "totp_fail_user", str(user.id), at)
    if link is not None:
        link.totp_failures += 1
        if link.totp_failures >= LINK_MAX_TOTP_FAILURES:
            link.used_at = at  # burned
    s.flush()
    if _over_limit(s, cfg, "totp_fail_user", str(user.id), at):
        _burn_links(s, user.id, at)
    return "totp_required"


def _burn_links(s: Session, user_id: uuid.UUID, at: datetime) -> None:
    s.execute(
        update(LoginToken)
        .where(LoginToken.user_id == user_id, LoginToken.used_at.is_(None))
        .values(used_at=at)
    )


def enroll_operator(engine: Engine, email: str, settings: Settings | None = None) -> bytes:
    """Give an existing user a fresh TOTP seed and the operator flag. Returns the raw seed once."""
    cfg = settings or load_settings()
    secret = totp.new_secret()
    with global_session(engine) as s:
        user = s.scalar(select(User).where(User.email == email))
        if user is None:
            raise NotFoundError("user")
        user.totp_secret_enc = seal(cfg.token_key, cfg.token_key_id, secret, TOTP_CONTEXT)
        user.totp_last_step = None
        user.is_operator = True
        # Sessions opened before the flag may carry a tenant; they end now (B2-S01).
        s.execute(delete(SessionRow).where(SessionRow.user_id == user.id))
    return secret


# ---------------------------------------------------------------- sessions


def _issue(
    engine: Engine, user_id: uuid.UUID, tenant_id: uuid.UUID | None, cfg: Settings, at: datetime
) -> IssuedSession:
    token = new_token()
    csrf = csrf_for(token, cfg)
    with global_session(engine) as s:
        user = s.get(User, user_id)
        if user is not None and user.is_operator:
            tenant_id = None  # B2-S01; the database trigger refuses it as well
        s.add(
            SessionRow(
                user_id=user_id,
                token_hash=hash_token(token),
                csrf_token_hash=hash_token(csrf),
                active_tenant_id=tenant_id,
                last_seen_at=at,
                expires_at=at + ABSOLUTE_LIFETIME,
                created_at=at,
            )
        )
    return IssuedSession(token=token, csrf_token=csrf, user_id=user_id, tenant_id=tenant_id)


def issue_session(
    engine: Engine,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> str:
    """Create a session and return the raw token. Used by sign-in and by test fixtures."""
    return _issue(engine, user_id, tenant_id, settings or load_settings(), _now(now)).token


def load_session(
    engine: Engine, token: str, now: datetime | None = None, touch: bool = True
) -> SessionContext | None:
    """Resolve a session cookie. Idle (60 min) and absolute (24 h) limits end the session for good;
    any authenticated request counts as activity and resets the idle timer."""
    at = _now(now)
    with global_session(engine) as s:
        row = s.scalar(select(SessionRow).where(SessionRow.token_hash == hash_token(token)).with_for_update())
        if row is None:
            return None
        user = s.get(User, row.user_id)
        tenant = s.get(Tenant, row.active_tenant_id) if row.active_tenant_id is not None else None
        if tenant is not None and tenant.status == "ended":
            s.delete(row)  # B2-S05: a session ends with its tenant
            return None
        if (
            row.ended_at is not None
            or at >= row.expires_at
            or at >= row.last_seen_at + IDLE_TIMEOUT
            or user is None
            or user.deactivated_at is not None
        ):
            s.delete(row)
            return None
        if touch:
            row.last_seen_at = at
        sid, uid, tid, csrf_hash = row.id, row.user_id, row.active_tenant_id, row.csrf_token_hash
        idle_deadline, absolute = row.last_seen_at + IDLE_TIMEOUT, row.expires_at
        is_operator = user.is_operator
    if is_operator:
        # B2-S01: an operator never acts in a tenant without an active support grant, and support
        # grants are not built, so an operator session carries no tenant on any path.
        tid = None
    role: str | None = None
    if tid is not None:
        with session(tid, engine) as s:
            role = s.scalar(
                select(Membership.role).where(Membership.user_id == uid, Membership.status == "active")
            )
        if role is None:
            tid = None
    return SessionContext(sid, uid, is_operator, tid, role, csrf_hash, min(idle_deadline, absolute), absolute)


def resolve_session(engine: Engine, token: str) -> Principal | None:
    ctx = load_session(engine, token)
    return ctx.principal() if ctx is not None else None


def end_session(engine: Engine, session_id: uuid.UUID) -> None:
    with global_session(engine) as s:
        s.execute(delete(SessionRow).where(SessionRow.id == session_id))


def switch_tenant(engine: Engine, ctx: SessionContext, tenant_id: uuid.UUID) -> None:
    if ctx.is_operator or tenant_id not in {m[0] for m in _active_memberships(engine, ctx.user_id)}:
        raise NotFoundError("tenant")
    with global_session(engine) as s:
        s.execute(
            update(SessionRow).where(SessionRow.id == ctx.session_id).values(active_tenant_id=tenant_id)
        )


def describe_me(engine: Engine, ctx: SessionContext) -> dict[str, Any]:
    with global_session(engine) as s:
        user = s.get(User, ctx.user_id)
        assert user is not None
        email, name = user.email, user.display_name
    return {
        "user": {
            "id": str(ctx.user_id),
            "email": email,
            "display_name": name,
            "is_operator": ctx.is_operator,
        },
        "memberships": [
            {"tenant_id": str(t), "role": r, "tenant_name": n}
            for t, r, n in _active_memberships(engine, ctx.user_id)
        ],
        "active_tenant_id": str(ctx.tenant_id) if ctx.tenant_id else None,
        "role": ctx.role,
        "idle_expires_at": ctx.idle_expires_at.isoformat(),
        "absolute_expires_at": ctx.absolute_expires_at.isoformat(),
    }


# ---------------------------------------------------------------- invitations


def create_invitation(
    engine: Engine,
    p: Principal,
    email: str,
    role: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], OutgoingMail]:
    if role not in ROLES:
        raise ValueError("unknown role")
    cfg = settings or load_settings()
    at = _now(now)
    token = new_token()
    with session(p.tenant_id, engine) as s:
        tenant = s.get(Tenant, p.tenant_id)
        assert tenant is not None
        inv = Invitation(
            tenant_id=p.tenant_id,
            email=email.strip(),
            role=role,
            token_hash=hash_token(token),
            invited_by=p.user_id,
            expires_at=at + INVITE_TTL,
            created_at=at,
        )
        s.add(inv)
        s.flush()
        write_audit(
            s,
            p.tenant_id,
            actor_type="user",
            actor_user_id=p.user_id,
            action="invitation_created",
            entity_type="invitation",
            entity_id=inv.id,
            after={"role": role},
        )
        body = _invitation_body(inv)
        tenant_name = tenant.name
    mail = OutgoingMail(
        to=email.strip(),
        subject=f"You are invited to {tenant_name} on MatchDesk",
        body=(
            f"You have been invited to join {tenant_name} on MatchDesk as {role}.\n\n"
            f"{cfg.app_base_url}/invite#t={token}\n\nThe invitation works once and expires in 7 days.\n"
        ),
    )
    return body, mail


def _invitation_body(inv: Invitation) -> dict[str, Any]:
    return {
        "id": str(inv.id),
        "email": inv.email,
        "role": inv.role,
        "expires_at": inv.expires_at.isoformat(),
        "accepted_at": inv.accepted_at.isoformat() if inv.accepted_at else None,
        "revoked_at": inv.revoked_at.isoformat() if inv.revoked_at else None,
    }


def list_invitations(engine: Engine, p: Principal, now: datetime | None = None) -> list[dict[str, Any]]:
    at = _now(now)
    with session(p.tenant_id, engine) as s:
        rows = s.scalars(
            select(Invitation)
            .where(
                Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None), Invitation.expires_at > at
            )
            .order_by(Invitation.created_at)
        ).all()
        return [_invitation_body(r) for r in rows]


def revoke_invitation(
    engine: Engine, p: Principal, invitation_id: uuid.UUID, now: datetime | None = None
) -> None:
    with session(p.tenant_id, engine) as s:
        inv = s.get(Invitation, invitation_id)
        if inv is None:
            raise NotFoundError("invitation")
        if inv.revoked_at is None and inv.accepted_at is None:
            inv.revoked_at = _now(now)
            write_audit(
                s,
                p.tenant_id,
                actor_type="user",
                actor_user_id=p.user_id,
                action="invitation_revoked",
                entity_type="invitation",
                entity_id=inv.id,
            )


def accept_invitation(
    engine: Engine, token: str, ip: str | None, settings: Settings | None = None, now: datetime | None = None
) -> IssuedSession:
    cfg = settings or load_settings()
    at = _now(now)
    th = hash_token(token)
    with global_session(engine) as s:
        if ip and _over_limit(s, cfg, "exchange_fail_ip", ip, at):
            raise AuthError("rate_limited")
    with invitation_lookup_session(th, engine) as s:
        inv = s.scalar(select(Invitation).where(Invitation.token_hash == th))
        found = (inv.tenant_id, inv.id) if inv is not None else None
    if found is None:
        _fail(engine, cfg, ip, at)
        raise AuthError("invalid")
    tenant_id, inv_id = found
    with global_session(engine) as s:
        tenant = s.get(Tenant, tenant_id)
        tenant_ok = tenant is not None and tenant.status != "ended"
    refusal: str | None = None
    user_id: uuid.UUID | None = None
    with session(tenant_id, engine) as s:
        inv = s.scalar(select(Invitation).where(Invitation.id == inv_id).with_for_update())
        assert inv is not None
        if not tenant_ok or inv.accepted_at is not None or inv.revoked_at is not None or inv.expires_at <= at:
            refusal = "invalid"
        else:
            found_user = _user_for_invitation(engine, inv.email)
            m = (
                s.scalar(select(Membership).where(Membership.user_id == found_user[0]))
                if found_user is not None
                else None
            )
            if found_user is None:
                refusal = "invalid"
            elif found_user[1]:
                # B2-S01: an operator never joins a tenant through an invitation, so an invitation
                # can never stand in for the one-time code; operators enter only by support grant.
                refusal = "operator_invitation"
            elif m is not None and m.status != "active":
                # B2-S03: a deactivated member is not re-activated by any invitation; only a
                # controller's PATCH /memberships/{id} can.
                refusal = "invalid"
            else:
                user_id = found_user[0]
                if m is None:
                    s.add(Membership(tenant_id=tenant_id, user_id=user_id, role=inv.role))
                inv.accepted_at = at
                write_audit(
                    s,
                    tenant_id,
                    actor_type="user",
                    actor_user_id=user_id,
                    action="invitation_accepted",
                    entity_type="invitation",
                    entity_id=inv.id,
                    after={"role": inv.role},
                )
    if refusal is not None or user_id is None:
        _fail(engine, cfg, ip, at)
        raise AuthError(refusal or "invalid")
    return _issue(engine, user_id, tenant_id, cfg, at)


def _fail(engine: Engine, cfg: Settings, ip: str | None, at: datetime) -> None:
    if ip:
        with global_session(engine) as s:
            _count_event(s, cfg, "exchange_fail_ip", ip, at)


def _user_for_invitation(engine: Engine, email: str) -> tuple[uuid.UUID, bool] | None:
    """(user id, is operator) for this address, creating the user if needed. A deactivated user is
    not revived."""
    with global_session(engine) as s:
        user = s.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email)
            s.add(user)
            s.flush()
        elif user.deactivated_at is not None:
            return None
        return user.id, user.is_operator


# ---------------------------------------------------------------- users and memberships


def list_users(engine: Engine, p: Principal) -> list[dict[str, Any]]:
    with session(p.tenant_id, engine) as s:
        rows = s.execute(
            select(Membership, User.email, User.display_name)
            .join(User, User.id == Membership.user_id)
            .order_by(User.email)
        ).all()
        return [
            {
                "membership_id": str(m.id),
                "user_id": str(m.user_id),
                "email": email,
                "display_name": name,
                "role": m.role,
                "status": m.status,
            }
            for m, email, name in rows
        ]


def update_membership(
    engine: Engine, p: Principal, membership_id: uuid.UUID, role: str | None, status: str | None
) -> dict[str, Any]:
    """Change a role or deactivate. Nobody changes their own membership; the database refuses to
    remove the last active controller; deactivation ends that user's sessions in this tenant."""
    if role is not None and role not in ROLES:
        raise ValueError("unknown role")
    if status is not None and status not in ("active", "deactivated"):
        raise ValueError("unknown status")
    try:
        with session(p.tenant_id, engine) as s:
            m = s.get(Membership, membership_id)
            if m is None:
                raise NotFoundError("membership")
            if m.user_id == p.user_id:
                raise ForbiddenError("own membership")
            before = {"role": m.role, "status": m.status}
            if role is not None:
                m.role = role
            if status is not None:
                m.status = status
            s.flush()
            write_audit(
                s,
                p.tenant_id,
                actor_type="user",
                actor_user_id=p.user_id,
                action="membership_changed",
                entity_type="membership",
                entity_id=m.id,
                before=before,
                after={"role": m.role, "status": m.status},
            )
            target, ended = m.user_id, m.status == "deactivated"
            if ended:
                # B2-S03: every open invitation to this person in the tenant is revoked with it.
                member = s.get(User, m.user_id)
                assert member is not None
                s.execute(
                    update(Invitation)
                    .where(
                        Invitation.email == member.email,
                        Invitation.accepted_at.is_(None),
                        Invitation.revoked_at.is_(None),
                    )
                    .values(revoked_at=func.now())
                )
            body = {"membership_id": str(m.id), "user_id": str(m.user_id), "role": m.role, "status": m.status}
    except DBAPIError as exc:
        if "last active controller" in str(exc.orig):
            raise ConflictError("cannot remove the last active controller") from exc
        raise
    if ended:
        with global_session(engine) as s:
            # B2-S03: all of the person's sessions end, not only those open in this tenant.
            s.execute(delete(SessionRow).where(SessionRow.user_id == target))
    return body
