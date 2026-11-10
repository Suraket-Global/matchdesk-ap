"""Declarative base, engine and the one place that sets the tenant (TRD 8.2, R-05).

``session(tenant_id)`` opens a transaction and runs ``set_config('app.tenant_id', ..., true)``
(the ``SET LOCAL`` form), so the setting lasts exactly one transaction and a
pooled connection never carries it into the next request. With no tenant set,
every row-level security policy matches nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache

from sqlalchemy import (
    DateTime,
    Engine,
    ForeignKeyConstraint,
    MetaData,
    UniqueConstraint,
    create_engine,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from matchdesk.core import TenantContextError, load_settings

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class GlobalMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TenantMixin(GlobalMixin):
    """Tenant-owned table: ``tenant_id``, unique ``(tenant_id, id)``; the policy is in the migration."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


def tenant_args(*extra: object) -> tuple:
    """``__table_args__`` for a tenant-owned table: unique ``(tenant_id, id)`` and FK to tenants."""
    return (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        *extra,
    )


def tfk(column: str, target_table: str, *, ondelete: str | None = None) -> ForeignKeyConstraint:
    """Composite foreign key ``(tenant_id, column) -> target(tenant_id, id)``."""
    return ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{target_table}.tenant_id", f"{target_table}.id"],
        ondelete=ondelete,
    )


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or load_settings().database_url, pool_pre_ping=True, future=True)


@contextmanager
def session(tenant_id: uuid.UUID | str, engine: Engine | None = None) -> Iterator[Session]:
    """Transaction with the tenant set. Commits on success, rolls back on error."""
    if not tenant_id:
        raise TenantContextError("tenant_id is required")
    tid = str(uuid.UUID(str(tenant_id)))
    with Session(engine or get_engine(), expire_on_commit=False) as s, s.begin():
        s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": tid})
        yield s


@contextmanager
def global_session(engine: Engine | None = None) -> Iterator[Session]:
    """Transaction with no tenant: global tables only; tenant tables read as empty."""
    with Session(engine or get_engine(), expire_on_commit=False) as s, s.begin():
        yield s


@contextmanager
def operator_session(engine: Engine | None = None) -> Iterator[Session]:
    """Operator path without a support grant: sets ``app.operator`` and never a tenant.

    In B1 no table carries an operator policy yet (pilot_engagements, usage_events
    and support_grants are not built), so this session sees no tenant row at all.
    """
    with Session(engine or get_engine(), expire_on_commit=False) as s, s.begin():
        s.execute(text("select set_config('app.operator', 'on', true)"))
        yield s
