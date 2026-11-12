"""B7 units: inbound signature (T-3.3.4), usage month in Pacific time (IT-26), week boundaries (S-14)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from matchdesk.core import load_settings
from matchdesk.intake import InboundRefused, sign, signing_key, usage_month, verify_signature
from matchdesk.reporting import week_of

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def test_signature_checked_and_provider_selected_by_settings() -> None:
    settings = replace(load_settings(), session_key="synthetic-session-key", env="test")
    body, ts = b'{"message_id": "x"}', str(int(NOW.timestamp()))
    verify_signature(settings, body, ts, sign(body, ts, signing_key(settings)), NOW)
    with pytest.raises(InboundRefused) as bad:
        verify_signature(settings, body + b" ", ts, sign(body, ts, signing_key(settings)), NOW)
    assert bad.value.status == 401
    with pytest.raises(InboundRefused) as hosted:
        verify_signature(replace(settings, inbound_provider="postmark"), body, ts, "x", NOW)
    assert hosted.value.status == 503  # a hosted provider needs its account: refused, not faked
    with pytest.raises(InboundRefused):
        signing_key(replace(settings, env="production", inbound_signing_key=""))


def test_usage_month_is_pacific_and_week_starts_monday() -> None:
    assert usage_month(datetime(2026, 11, 1, 6, 30, tzinfo=UTC)) == date(2026, 10, 1)
    assert usage_month(datetime(2026, 11, 1, 8, 30, tzinfo=UTC)) == date(2026, 11, 1)
    assert week_of(date(2026, 10, 11)) == date(2026, 10, 5)
    assert week_of(date(2026, 10, 5)) == date(2026, 10, 5)
