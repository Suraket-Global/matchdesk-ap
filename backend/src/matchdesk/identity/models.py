"""Accounts and identity tables (schema.md 3.1): tenants, users, memberships, invitations, sign-in
links, sessions, and the counters behind sign-in rate limits (B1, B2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy import MONEY, UUIDT, Base, GlobalMixin, TenantMixin, enum_check, tenant_args

ROLES = ("controller", "clerk", "viewer")


class Tenant(GlobalMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(enum_check("status", ("pilot", "active", "ended")), name="status"),
        CheckConstraint("waiver_limit >= 0 and waiver_period_cap >= waiver_limit", name="waiver_limits"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pilot")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="CAD")
    # Waiver above this per exception, or above the cap over a rolling 30 days, needs the controller
    # (schema.md 3.1; PRD MH-11 defaults [assumption]).
    waiver_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="100.00")
    waiver_period_cap: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="500.00")
    # Local part of the account's intake address (``<local>@<intake domain>``); unique (B7, T-3.3.4).
    intake_address_local: Mapped[str | None] = mapped_column(Text, unique=True)


class User(GlobalMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("not is_operator or totp_secret_enc is not null", name="operator_needs_totp"),
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    is_operator: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # AES-256-GCM sealed TOTP seed (S3); last accepted 30-second step, so a code is used once (B2).
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(TenantMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint(enum_check("role", ROLES), name="role"),
        CheckConstraint(enum_check("status", ("active", "deactivated")), name="status"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")


class Invitation(TenantMixin, Base):
    """Open invitation (T-2.2.3 (c)). Found without a tenant only by the hash of its token."""

    __tablename__ = "invitations"
    __table_args__ = tenant_args(CheckConstraint(enum_check("role", ROLES), name="role"))
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginToken(GlobalMixin, Base):
    """Emailed sign-in link (T-2.2.3 (a)): hash of a 256-bit token, bound to the requesting browser."""

    __tablename__ = "login_tokens"
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    browser_binding_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # No longer written (B2-S06); kept null until a later contract migration drops it.
    requested_ip: Mapped[str | None] = mapped_column(INET)
    # Wrong one-time codes against this link; the link is burned at the limit (B2-S02).
    totp_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class AuthRateEvent(GlobalMixin, Base):
    """One counted sign-in event; the key is an HMAC of the address, IP or user ID under a server key."""

    __tablename__ = "auth_rate_events"
    __table_args__ = (
        CheckConstraint(
            enum_check("kind", ("link_address", "link_ip", "exchange_fail_ip", "totp_fail_user")), name="kind"
        ),
        Index("ix_auth_rate_events_kind_key_hash_created_at", "kind", "key_hash", "created_at"),
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class SessionRow(GlobalMixin, Base):
    """Server-side session (global). Ended by deleting the row (sign-out, deactivation)."""

    __tablename__ = "sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    csrf_token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    active_tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("tenants.id"))
    # Set when an operator entered the tenant as ``support_reader`` under this grant (B7, S-18).
    support_grant_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


GRANT_STATES = ("requested", "active", "ended", "declined")


class SupportGrant(TenantMixin, Base):
    """Read-only support access for the operator, requested by the operator and granted by a
    controller of the tenant, for at most 7 days (schema.md 3.1; B7, T-5.1.5)."""

    __tablename__ = "support_grants"
    __table_args__ = tenant_args(
        CheckConstraint(enum_check("status", GRANT_STATES), name="status"),
        CheckConstraint("hours_requested between 1 and 168", name="hours_requested"),
        CheckConstraint(
            "ends_at is null or (ends_at > starts_at and ends_at <= starts_at + interval '7 days')",
            name="window",
        ),
        CheckConstraint(
            "status not in ('active', 'ended') or (granted_by is not null and starts_at is not null "
            "and ends_at is not null)",
            name="granted_has_window",
        ),
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    hours_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="requested")
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_early_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("users.id"))
