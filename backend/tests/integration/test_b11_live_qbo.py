"""B11 integration: QuickBooks mode per tenant, the Intuit connect path beside the recorded demo,
token refresh before expiry and after a 401 with one refresher per connection, needs_reconnect in
its own transaction. The fake token endpoint stands in for Intuit; nothing reaches the network."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from matchdesk.api.app import create_app
from matchdesk.core import ConflictError, load_settings
from matchdesk.identity import Membership, Tenant, User, issue_session
from matchdesk.qbo import (
    FakeIntuitTokenEndpoint,
    IntuitQboReader,
    QboNotConfiguredError,
    RecordedQboReader,
    access_token,
    execute_sync,
    reader_for_tenant,
    request_sync,
    token_source,
)
from matchdesk.qbo.models import QboConnection, SyncRun
from matchdesk.tenancy import PermanentJobError, global_session, session

from .seed import auth_headers

pytestmark = pytest.mark.integration
BASE = "https://app.matchdesk.test"  # the tests' MATCHDESK_APP_BASE_URL (tests/conftest.py)


def tenant(engine, mode: str | None) -> tuple[uuid.UUID, uuid.UUID, str]:  # type: ignore[no-untyped-def]
    with global_session(engine) as s:
        t = Tenant(name=f"Fictional Sandbox Distributor {uuid.uuid4().hex[:6]}", qbo_mode=mode)
        u = User(email=f"{uuid.uuid4().hex[:8]}@example.invalid", display_name="Synthetic controller")
        s.add_all([t, u])
        s.flush()
        tid, uid = t.id, u.id
    with session(tid, engine) as s:
        s.add(Membership(tenant_id=tid, user_id=uid, role="controller"))
    return tid, uid, issue_session(engine, uid, tid)


@pytest.fixture
def configured(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MATCHDESK_QBO_CLIENT_ID", "client-id-invented")
    monkeypatch.setenv("MATCHDESK_QBO_CLIENT_SECRET", "client-secret-invented")
    monkeypatch.setenv("MATCHDESK_QBO_REDIRECT_URI", f"{BASE}/oauth/intuit/callback")


def connect(client: TestClient, endpoint: FakeIntuitTokenEndpoint, token: str, realm: str) -> str:
    r = client.post("/api/v1/qbo/connection/authorize", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    cb = client.get(
        "/oauth/intuit/callback",
        params={"state": state, "code": endpoint.issue_code(), "realmId": realm},
        headers={"Cookie": f"__Host-md_session={token}"},
        follow_redirects=False,
    )
    assert cb.status_code == 303
    return str(cb.headers["location"])


def test_intuit_tenant_connects_beside_a_recorded_tenant(app_engine, configured):  # type: ignore[no-untyped-def]
    endpoint = FakeIntuitTokenEndpoint()
    client = TestClient(create_app(qbo_token_endpoint=endpoint))
    tid, _uid, token = tenant(app_engine, "intuit")
    _rtid, _ruid, rtoken = tenant(app_engine, None)

    r = client.post("/api/v1/qbo/connection/authorize", headers=auth_headers(token))
    url = urlparse(r.json()["authorization_url"])
    q = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == load_settings().qbo_authorize_url
    assert q["scope"] == ["com.intuit.quickbooks.accounting"]  # the only scope asked for
    assert q["redirect_uri"] == [f"{BASE}/oauth/intuit/callback"]
    assert q["client_id"] == ["client-id-invented"] and q["response_type"] == ["code"]

    assert connect(client, endpoint, token, f"realm-{tid}").endswith("result=connected")
    live = client.get("/api/v1/qbo/connection", headers=auth_headers(token)).json()
    assert live["status"] == "connected" and live["mode"] == "intuit" and live["source"] == "intuit"
    assert live["intuit_environment"] == "sandbox"
    demo = client.get("/api/v1/qbo/connection", headers=auth_headers(rtoken)).json()
    assert demo["mode"] == "recorded" and demo["source"] == "demo_data" and demo["intuit_environment"] is None

    # The sync reader follows the tenant: Intuit for this one, recorded responses for the other.
    settings = load_settings()
    reader = reader_for_tenant(app_engine, settings, tid, endpoint)
    assert isinstance(reader, IntuitQboReader) and reader.api is not None
    assert isinstance(reader_for_tenant(app_engine, settings, _rtid), RecordedQboReader)
    # Phase A: the live reader is not written yet, so a read fails plainly and copies nothing.
    with session(tid, app_engine) as s:
        run, _ = request_sync(s, tid, _uid, "po_references", references=["1001"])
    with pytest.raises(PermanentJobError):
        execute_sync(app_engine, tid, run.id, reader, settings.qbo_page_size)
    with session(tid, app_engine) as s:
        done = s.get(SyncRun, run.id)
        assert done is not None and done.state == "failed" and done.error_code == "QboNotConfiguredError"


def test_intuit_connect_refused_off_the_redirect_origin_or_unconfigured(app_engine, monkeypatch):  # type: ignore[no-untyped-def]
    _tid, _uid, token = tenant(app_engine, "intuit")
    unconfigured = TestClient(create_app(qbo_token_endpoint=FakeIntuitTokenEndpoint()))
    assert (
        unconfigured.post("/api/v1/qbo/connection/authorize", headers=auth_headers(token)).status_code == 503
    )

    monkeypatch.setenv("MATCHDESK_QBO_CLIENT_ID", "client-id-invented")
    monkeypatch.setenv("MATCHDESK_QBO_CLIENT_SECRET", "client-secret-invented")
    monkeypatch.setenv("MATCHDESK_QBO_REDIRECT_URI", "http://localhost:5173/oauth/intuit/callback")
    elsewhere = TestClient(create_app(qbo_token_endpoint=FakeIntuitTokenEndpoint()))
    r = elsewhere.post("/api/v1/qbo/connection/authorize", headers=auth_headers(token))
    assert r.status_code == 409 and "http://localhost:5173" in r.text


def _connected(app_engine, endpoint):  # type: ignore[no-untyped-def]
    client = TestClient(create_app(qbo_token_endpoint=endpoint))
    tid, _uid, token = tenant(app_engine, None)
    assert connect(client, endpoint, token, f"realm-{tid}").endswith("result=connected")
    return tid


def _expire_in(app_engine, tid, delta: timedelta) -> None:  # type: ignore[no-untyped-def]
    with session(tid, app_engine) as s:
        s.execute(text("update qbo_connections set access_expires_at = :t"), {"t": datetime.now(UTC) + delta})


def test_refresh_shortly_before_expiry_not_earlier(app_engine):  # type: ignore[no-untyped-def]
    endpoint = FakeIntuitTokenEndpoint()
    tid = _connected(app_engine, endpoint)
    settings = load_settings()
    get = token_source(app_engine, settings, endpoint, tid)
    first = get(None)
    assert endpoint.refresh_calls == 0 and get(None) == first  # an hour left: no refresh
    _expire_in(app_engine, tid, timedelta(minutes=2))  # inside the 5-minute window
    second = get(None)
    assert endpoint.refresh_calls == 1 and second != first
    with session(tid, app_engine) as s:
        conn = s.scalar(select(QboConnection))
        assert conn is not None and conn.access_expires_at > datetime.now(UTC) + timedelta(minutes=50)


def test_a_401_refreshes_once_for_concurrent_callers(app_engine):  # type: ignore[no-untyped-def]
    endpoint = FakeIntuitTokenEndpoint(refresh_delay_ms=300)
    tid = _connected(app_engine, endpoint)
    settings = load_settings()
    refused = token_source(app_engine, settings, endpoint, tid)(None)
    results: list[str] = []
    errors: list[BaseException] = []

    def caller() -> None:
        try:
            results.append(token_source(app_engine, settings, endpoint, tid)(refused))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=caller) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert endpoint.refresh_calls == 1  # one refresher per connection
    assert len(set(results)) == 1 and results[0] != refused


def test_refused_refresh_marks_needs_reconnect_through_the_token_source(app_engine):  # type: ignore[no-untyped-def]
    endpoint = FakeIntuitTokenEndpoint()
    tid = _connected(app_engine, endpoint)
    settings = load_settings()
    get = token_source(app_engine, settings, endpoint, tid)
    current = get(None)
    endpoint.expire_refresh = True
    with pytest.raises(ConflictError):
        get(current)  # the 401 path
    with session(tid, app_engine) as s:
        conn = s.scalar(select(QboConnection))
        assert conn is not None and conn.status == "needs_reconnect"
    with pytest.raises(ConflictError), session(tid, app_engine) as s:
        access_token(s, settings, endpoint, tid)  # no token is handed out after that
    with pytest.raises(QboNotConfiguredError):
        IntuitQboReader(settings).page("Vendor", 1, 10, None)  # type: ignore[arg-type]
