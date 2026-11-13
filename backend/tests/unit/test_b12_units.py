"""B12 units: the rule for deleting one document, and its permission row (schema.md 4.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from matchdesk.exceptions.document_removal import removal_rule
from matchdesk.tenancy import can


def _doc(state: str = "needs_review", purpose: str = "invoice", removed: bool = False) -> SimpleNamespace:
    return SimpleNamespace(state=state, purpose=purpose, removed_at=datetime.now(UTC) if removed else None)


def _inv(status: str) -> SimpleNamespace:
    return SimpleNamespace(verification_status=status)


@pytest.mark.parametrize("status", ["passed", "human_confirmed", "human_confirmed_inconsistent"])
def test_an_accepted_document_needs_the_controller_and_a_reason(status: str) -> None:
    rule = removal_rule(_doc("succeeded"), [_inv("failed"), _inv(status)])  # type: ignore[arg-type]
    assert rule == {"accepted": True, "needs_controller": True, "reason_required": True, "blocked": None}


def test_a_document_no_one_accepted_is_deleted_by_a_clerk_without_a_reason() -> None:
    rule = removal_rule(_doc(), [_inv("failed")])  # type: ignore[arg-type]
    assert not rule["needs_controller"] and not rule["reason_required"] and rule["blocked"] is None
    assert removal_rule(_doc("failed"), [])["blocked"] is None  # type: ignore[arg-type]


@pytest.mark.parametrize("state", ["queued", "running", "retry_wait"])
def test_a_document_still_being_read_is_not_deleted(state: str) -> None:
    assert "still being read" in removal_rule(_doc(state), [])["blocked"]  # type: ignore[arg-type]


def test_other_files_and_deleted_documents_are_refused() -> None:
    assert removal_rule(_doc(purpose="receiving"), [])["blocked"]  # type: ignore[arg-type]
    assert "already deleted" in removal_rule(_doc(removed=True), [])["blocked"]  # type: ignore[arg-type]


def test_permission_rows() -> None:
    assert can("controller", "delete_document") and can("clerk", "delete_document")
    assert not can("viewer", "delete_document") and not can("support_reader", "delete_document")
    assert can("controller", "read_usage") and not can("clerk", "read_usage")


def _seed_sandbox():  # type: ignore[no-untyped-def]
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "seed_sandbox.py"
    spec = importlib.util.spec_from_file_location("seed_sandbox_b12", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_sandbox_takes_a_name_and_a_currency() -> None:
    m = _seed_sandbox()
    us = m.parse_args([])
    assert (us.name, us.currency, us.controller) == (m.TENANT, "USD", "controller.sandbox@example.invalid")
    ca = m.parse_args(["--name", "Sandbox Distributor CA (Intuit sandbox)", "--currency", "cad"])
    assert ca.currency == "CAD" and ca.name == "Sandbox Distributor CA (Intuit sandbox)"
    assert (ca.controller, ca.clerk) == (
        "controller.sandbox-ca@example.invalid",
        "clerk.sandbox-ca@example.invalid",
    )
    with pytest.raises(SystemExit):
        m.parse_args(["--currency", "EUR"])  # no defaults: names and addresses must be given
    with pytest.raises(SystemExit):
        m.parse_args(["--currency", "CAD", "--controller", "real.person@example.com"])
    with pytest.raises(SystemExit):
        m.parse_args(["--currency", "C1D"])
