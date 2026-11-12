"""Exceptions, match results and match runs."""

from matchdesk.exceptions.inputs import build_match_input
from matchdesk.exceptions.permissions import check_resolution_allowed
from matchdesk.exceptions.runs import TASK as MATCH_RUN_TASK
from matchdesk.exceptions.runs import execute_run, rematch_alias, request_run, stale_runs
from matchdesk.exceptions.store import exception_fingerprint, store_result
from matchdesk.exceptions.triggers import TASK as MATCH_REQUEST_TASK
from matchdesk.exceptions.triggers import (
    handle_match_request,
    invoices_on_po_lines,
    invoices_on_pos,
    related_invoices,
    request_runs,
)

__all__ = [
    "MATCH_REQUEST_TASK",
    "MATCH_RUN_TASK",
    "build_match_input",
    "check_resolution_allowed",
    "exception_fingerprint",
    "execute_run",
    "handle_match_request",
    "invoices_on_po_lines",
    "invoices_on_pos",
    "related_invoices",
    "rematch_alias",
    "request_run",
    "request_runs",
    "stale_runs",
    "store_result",
]
