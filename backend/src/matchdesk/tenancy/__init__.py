"""Tenant context, database sessions, job wrapper and state transitions (kernel)."""

from matchdesk.tenancy.db import (
    Base,
    GlobalMixin,
    TenantMixin,
    get_engine,
    global_session,
    invitation_lookup_session,
    operator_session,
    session,
    tenant_args,
    tfk,
    user_session,
)
from matchdesk.tenancy.jobs import (
    ClaimedJob,
    PermanentJobError,
    claim,
    enqueue,
    enqueue_raw,
    run_claimed,
)
from matchdesk.tenancy.permissions import PERMISSIONS, can, permissions_for
from matchdesk.tenancy.secrets_box import SealError, seal, unseal
from matchdesk.tenancy.transitions import advisory_lock, lock_for_update, transition
from matchdesk.tenancy.types import MONEY, PRICE, QTY, UUIDT, enum_check

__all__ = [
    "MONEY",
    "PERMISSIONS",
    "PRICE",
    "QTY",
    "UUIDT",
    "Base",
    "ClaimedJob",
    "GlobalMixin",
    "PermanentJobError",
    "SealError",
    "TenantMixin",
    "advisory_lock",
    "can",
    "claim",
    "enqueue",
    "enqueue_raw",
    "enum_check",
    "get_engine",
    "global_session",
    "invitation_lookup_session",
    "lock_for_update",
    "operator_session",
    "permissions_for",
    "run_claimed",
    "seal",
    "session",
    "tenant_args",
    "tfk",
    "transition",
    "unseal",
    "user_session",
]
