"""B2 unit tests: TOTP (RFC 6238 vectors), sealing, anti-forgery token, permission table, mail fake."""

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime

import pytest

from matchdesk.core import OutgoingMail, RecordingMailer
from matchdesk.identity import csrf_for
from matchdesk.identity.secrets_box import SealError, seal, unseal
from matchdesk.identity.totp import code_at_step, step_at, verify
from matchdesk.tenancy import PERMISSIONS, can

RFC_SECRET = b"12345678901234567890"


@pytest.mark.parametrize(
    ("unix", "eight_digits"),
    [(59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"), (2000000000, "69279037")],
)
def test_totp_matches_rfc_6238_sha1_vectors(unix: int, eight_digits: str) -> None:
    # The RFC lists 8-digit codes; a 6-digit code is the same value modulo 10**6.
    assert code_at_step(RFC_SECRET, unix // 30) == eight_digits[-6:]


def test_totp_accepts_one_step_of_drift_and_each_step_once() -> None:
    now = datetime(2026, 11, 11, 12, 0, 15, tzinfo=UTC)
    step = step_at(now)
    assert verify(RFC_SECRET, code_at_step(RFC_SECRET, step - 1), now, None) == step - 1
    assert verify(RFC_SECRET, code_at_step(RFC_SECRET, step + 2), now, None) is None
    assert verify(RFC_SECRET, code_at_step(RFC_SECRET, step), now, step) is None  # reused
    assert verify(RFC_SECRET, "12345", now, None) is None
    assert verify(RFC_SECRET, "abcdef", now, None) is None


def test_seal_round_trip_and_refusals() -> None:
    key = base64.b64encode(os.urandom(32)).decode()
    other = base64.b64encode(os.urandom(32)).decode()
    sealed = seal(key, "k1", b"seed", b"ctx")
    assert b"seed" not in sealed
    assert unseal({"k1": key}, sealed, b"ctx") == b"seed"
    with pytest.raises(SealError):
        unseal({"k1": other}, sealed, b"ctx")
    with pytest.raises(SealError):
        unseal({"k1": key}, sealed, b"other context")
    with pytest.raises(SealError):
        unseal({"k2": key}, sealed, b"ctx")


def test_csrf_token_is_bound_to_the_session_token() -> None:
    a, b = csrf_for("session-token-a"), csrf_for("session-token-b")
    assert a != b and a == csrf_for("session-token-a") and len(a) >= 40


def test_permission_table_follows_schema_4_1() -> None:
    assert can("controller", "manage_users") and not can("clerk", "manage_users")
    assert can("clerk", "upload_and_receiving") and not can("viewer", "upload_and_receiving")
    assert can("viewer", "read") and not can("operator", "read")
    assert not can("controller", "operator_tenants") and can("operator", "operator_tenants")
    assert not can("controller", "no_such_action")
    assert all(roles for roles in PERMISSIONS.values())


def test_recording_mailer_keeps_messages() -> None:
    m = RecordingMailer()
    m.send(OutgoingMail("a@example.invalid", "s", "b"))
    assert [x.to for x in m.sent] == ["a@example.invalid"]
