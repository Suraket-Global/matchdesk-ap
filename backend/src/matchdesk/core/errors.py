"""Error types shared by both entry points."""

from __future__ import annotations


class MatchDeskError(Exception):
    """Base error."""


class NotFoundError(MatchDeskError):
    """Missing record, or a record in another tenant: the two are reported identically."""


class ForbiddenError(MatchDeskError):
    """Permitted record, forbidden action."""


class ConflictError(MatchDeskError):
    """Version mismatch or idempotency-key reuse with a different request."""


class TenantContextError(MatchDeskError):
    """No tenant context where one is required."""
