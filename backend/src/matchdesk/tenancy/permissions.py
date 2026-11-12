"""The permission table of schema.md section 4.1 as data, and the one function that reads it
(T-2.2.3 (d); B2). Screens and endpoints never decide a permission on their own.

Columns: controller, clerk, viewer, operator without a grant, operator with a grant
(``support_reader``). Since B7 an operator session inside an active support grant carries the
role ``support_reader``: read rows only.
"""

from __future__ import annotations

ROLES = ("controller", "clerk", "viewer", "operator", "support_reader")

_C, _K, _V, _O, _S = ROLES

# action -> roles allowed. Row order follows schema.md 4.1.
PERMISSIONS: dict[str, frozenset[str]] = {
    "read": frozenset({_C, _K, _V, _S}),
    "export_report": frozenset({_C, _K, _V, _S}),
    "read_audit": frozenset({_C, _S}),
    "upload_and_receiving": frozenset({_C, _K}),
    "attest_receiving": frozenset({_C}),
    "correct_extraction": frozenset({_C, _K}),
    "edit_alias": frozenset({_C, _K}),
    "approve": frozenset({_C}),
    "resolve_exception": frozenset({_C, _K}),
    "confirm_not_received": frozenset({_C}),
    "withdraw_own_resolution": frozenset({_C, _K}),
    "reopen_exception": frozenset({_C}),
    "read_tolerances": frozenset({_C, _K, _V, _S}),
    "edit_tolerances": frozenset({_C}),
    "connect_qbo": frozenset({_C}),
    "start_sync": frozenset({_C, _K}),
    "draft_report": frozenset({_C, _K}),
    "approve_report": frozenset({_C}),
    "manage_users": frozenset({_C}),
    "edit_intake_settings": frozenset({_C}),
    "release_held_email": frozenset({_C, _K}),
    "read_usage": frozenset({_C}),
    "request_deletion_or_archive": frozenset({_C}),
    "operator_tenants": frozenset({_O, _S}),
    "enter_support_session": frozenset({_S}),
    # TRD 12: POST /match-runs is C K (re-match a scope); not a row of its own in schema.md 4.1.
    "start_match_run": frozenset({_C, _K}),
    # B7, T-5.1.4: "Send now" for the weekly summary email (a row added to schema.md 4.1).
    "send_weekly_summary": frozenset({_C}),
    # B9 rows added to schema.md 4.1: assign an exception (S-08); decide a possible duplicate or a
    # possible credit (S-09; MH-08, MH-09); record a finding's outcome on the governing report (S-13).
    "assign_exception": frozenset({_C, _K}),
    "decide_duplicate_or_credit": frozenset({_C}),
    "record_finding_outcome": frozenset({_C}),
}


def can(role: str, action: str) -> bool:
    """True when ``role`` may perform ``action``. An unknown action is refused."""
    allowed = PERMISSIONS.get(action)
    return allowed is not None and role in allowed


def permissions_for(role: str) -> list[str]:
    return sorted(a for a, roles in PERMISSIONS.items() if role in roles)
