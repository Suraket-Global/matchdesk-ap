"""Imports every ORM module so ``Base.metadata`` is complete (migrations and parity checks)."""

from __future__ import annotations

from matchdesk.tenancy.db import Base


def load_all_models() -> type[Base]:
    import matchdesk.audit.models
    import matchdesk.exceptions.models
    import matchdesk.extraction.models
    import matchdesk.identity.models
    import matchdesk.intake.models
    import matchdesk.qbo.models
    import matchdesk.receiving.models
    import matchdesk.reporting.models
    import matchdesk.tenancy.models  # noqa: F401

    return Base


GLOBAL_TABLES = frozenset(
    {
        "tenants",
        "users",
        "sessions",
        "login_tokens",
        "auth_rate_events",
        "ruleset_versions",
        "job_queue",
        "alembic_version",
        "deletion_ledger",
        # B10: the worker's scheduled operations; names and times only, no tenant data.
        "scheduled_operations",
    }
)
