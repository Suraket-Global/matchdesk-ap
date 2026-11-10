"""Who may resolve what (PRD MH-07; schema.md 3.6). The full permission table is T-2.2.3."""

from __future__ import annotations

from matchdesk.core import ForbiddenError

CONTROLLER_ONLY = frozenset({"confirmed_not_received"})
ALLOWED_FOR_RECEIPT_ABSENT = frozenset(
    {"confirmed_not_received", "resolved_by_credit", "source_corrected", "waived"}
)


def check_resolution_allowed(role: str, exception_type: str, code: str, *, bulk: bool = False) -> None:
    if role not in ("controller", "clerk"):
        raise ForbiddenError("this role cannot resolve exceptions")
    if code in CONTROLLER_ONLY and role != "controller":
        raise ForbiddenError("only the controller may confirm that goods were not received")
    if exception_type == "receipt_absent":
        if code not in ALLOWED_FOR_RECEIPT_ABSENT:
            raise ForbiddenError("an absent receipt cannot be resolved with this code")
        if bulk and code == "waived":
            raise ForbiddenError("receipt_absent cannot be waived in bulk")
