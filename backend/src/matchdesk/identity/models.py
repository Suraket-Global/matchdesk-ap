"""Accounts and identity tables used in B1 (schema.md 3.1): tenants, users, memberships, sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from matchdesk.tenancy import UUIDT, Base, GlobalMixin, TenantMixin, enum_check, tenant_args


class Tenant(GlobalMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint(enum_check("status", ("pilot", "active", "ended")), name="status"),)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pilot")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="CAD")


class User(GlobalMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    is_operator: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(TenantMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint(enum_check("role", ("controller", "clerk", "viewer")), name="role"),
        CheckConstraint(enum_check("status", ("active", "deactivated")), name="status"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")


class SessionRow(GlobalMixin, Base):
    """Server-side session (global). B1 issues sessions only from fixtures; sign-in links are T-2.2.3."""

    __tablename__ = "sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    active_tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("tenants.id"))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
