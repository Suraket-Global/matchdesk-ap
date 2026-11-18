"""Fixes from the live QuickBooks test of 2026-11-18."""

from __future__ import annotations

from datetime import date

from matchdesk.matching import fingerprint, input_fingerprint

from .builders import build, invoice


def test_engine_version_is_part_of_the_fingerprint(monkeypatch):
    """A change to the rules' code must make stored results out of date, so the worker's minute
    tick matches them again; the same inputs under the same engine still hash alike."""
    inp = build(docs=(invoice("i1", "INV-1", date(2026, 10, 8), "10"),))
    before = input_fingerprint(inp)
    assert input_fingerprint(inp) == before
    monkeypatch.setattr(fingerprint, "ENGINE_VERSION", "next")
    assert input_fingerprint(inp) != before


def test_email_intake_is_off_in_production_without_a_real_domain():
    from dataclasses import replace as dc_replace

    from matchdesk.core import load_settings
    from matchdesk.intake import email_intake_on

    base = load_settings()
    assert (
        email_intake_on(dc_replace(base, env="production", intake_domain="intake.matchdesk.invalid")) is False
    )
    assert email_intake_on(dc_replace(base, env="production", intake_domain="in.example.com")) is True
    assert (
        email_intake_on(dc_replace(base, env="development", intake_domain="intake.matchdesk.invalid")) is True
    )
