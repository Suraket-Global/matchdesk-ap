"""Tenant context, database sessions, job wrapper and state transitions (kernel)."""

from matchdesk.tenancy.db import Base, get_engine, global_session, operator_session, session
from matchdesk.tenancy.jobs import (
    ClaimedJob,
    PermanentJobError,
    claim,
    enqueue,
    enqueue_raw,
    run_claimed,
)
from matchdesk.tenancy.transitions import transition

__all__ = [
    "Base",
    "ClaimedJob",
    "PermanentJobError",
    "claim",
    "enqueue",
    "enqueue_raw",
    "get_engine",
    "global_session",
    "operator_session",
    "run_claimed",
    "session",
    "transition",
]
