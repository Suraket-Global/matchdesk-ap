"""Trial guidance (owner, 2026-11-19): the tour state, the trial's next step, the operator's view of
each trial and the day 1 / 3 / 6 reminder emails."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from matchdesk.api.app import create_app
from matchdesk.audit.models import AuditEvent
from matchdesk.core import RecordingMailer, load_settings
from matchdesk.identity.models import Tenant
from matchdesk.reporting import due_trial_nudges
from matchdesk.tenancy import global_session, session

from .seed import add_invoice, add_user, make_tenant
from .test_b7_pieces import make_operator


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app(mailer=RecordingMailer()))


def _trial(engine, w, started: datetime) -> None:  # type: ignore[no-untyped-def]
    with global_session(engine) as g:
        t = g.get(Tenant, w.tenant_id)
        assert t is not None
        t.status, t.sample_ends_at, t.trial_nudges = "sample", started + timedelta(days=7), []


def test_the_tour_is_offered_once_and_can_be_taken_again(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, f"Fictional Tourco {uuid.uuid4().hex[:6]}")
    assert client.get("/api/v1/me", headers=w.headers).json()["tour_state"] is None
    r = client.put("/api/v1/me/tour", json={"state": "skipped"}, headers=w.headers)
    assert r.status_code == 200 and r.json() == {"tour_state": "skipped"}
    assert client.get("/api/v1/me", headers=w.headers).json()["tour_state"] == "skipped"
    assert client.put("/api/v1/me/tour", json={"state": None}, headers=w.headers).json()["tour_state"] is None
    assert (
        client.put("/api/v1/me/tour", json={"state": "done"}, headers=w.headers).json()["tour_state"]
        == "done"
    )
    assert client.put("/api/v1/me/tour", json={"state": "later"}, headers=w.headers).status_code == 422


def test_the_trial_names_its_day_and_next_step(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, f"Fictional Stepco {uuid.uuid4().hex[:6]}")
    _trial(app_engine, w, datetime.now(UTC) - timedelta(days=2, hours=1))
    st = client.get("/api/v1/me", headers=w.headers).json()["sample"]
    assert st["day"] == 3 and st["days"] == 7
    assert st["progress"]["next_step"] == "connect_qbo" and st["progress"]["steps_done"] == 0
    add_invoice(app_engine, w, "t1", "INV-TRIAL-1", date(2026, 10, 6), "10")
    p = client.get("/api/v1/me", headers=w.headers).json()["sample"]["progress"]
    assert p["invoices"] == 1 and p["next_step"] == "connect_qbo"  # QuickBooks still comes first


def test_the_operator_sees_how_far_each_trial_has_got(app_engine, client):  # type: ignore[no-untyped-def]
    _op, oh = make_operator(app_engine)
    w = make_tenant(app_engine, f"Fictional Watchco {uuid.uuid4().hex[:6]}")
    _trial(app_engine, w, datetime.now(UTC) - timedelta(hours=3))
    rows = {t["id"]: t for t in client.get("/api/v1/operator/tenants", headers=oh).json()["items"]}
    trial = rows[str(w.tenant_id)]["trial"]
    assert trial["day"] == 1 and trial["progress"]["qbo_connected"] is False
    assert set(trial["progress"]) >= {"receiving_loaded", "invoices", "findings", "next_step"}


def test_reminders_go_once_to_the_controllers_with_the_next_step(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, f"Fictional Nudgeco {uuid.uuid4().hex[:6]}")
    add_user(app_engine, w, "controller")
    start = datetime.now(UTC) - timedelta(hours=1)
    _trial(app_engine, w, start)
    mail, settings = RecordingMailer(), load_settings()

    def mine() -> list:  # type: ignore[type-arg]
        return [m for m in mail.sent if "Nudgeco" in m.body]

    due_trial_nudges(app_engine, start + timedelta(hours=2), mail, settings)
    assert mine() == []  # nothing due in the first hours
    due_trial_nudges(app_engine, start + timedelta(hours=21), mail, settings)
    assert len(mine()) == 1  # the controller only, not the clerk
    assert (
        "Next step: Connect QuickBooks Online" in mine()[0].body and "/settings/quickbooks" in mine()[0].body
    )
    due_trial_nudges(app_engine, start + timedelta(hours=22), mail, settings)
    assert len(mine()) == 1  # day 1 goes once
    # A run late on day 6 sends only the day-6 reminder, never day 3 and day 6 together.
    due_trial_nudges(app_engine, start + timedelta(hours=141), mail, settings)
    assert len(mine()) == 2 and "ends tomorrow" in mine()[-1].subject
    with global_session(app_engine) as g:
        t = g.get(Tenant, w.tenant_id)
        assert t is not None and t.trial_nudges == ["day1", "day3", "day6"]
    with session(w.tenant_id, app_engine) as s:
        kinds = sorted(
            e.after["kind"]
            for e in s.scalars(select(AuditEvent).where(AuditEvent.action == "trial.reminder_sent"))
        )
    assert kinds == ["day1", "day6"]
    # After the trial ends, nothing more is sent.
    due_trial_nudges(app_engine, start + timedelta(days=8), mail, settings)
    assert len(mine()) == 2
