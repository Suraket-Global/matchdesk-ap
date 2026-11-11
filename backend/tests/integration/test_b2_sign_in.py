"""B2 sign-in (IT-18 subset, IT-13 subset; TRD 8.1; T-2.2.3).

The first group reads every link from the local Mailpit inbox. The second group (security fixes
after the B2 review, round 1) keeps each attack case and mutation of
`_coordination/review/matchdesk-ap-b2-sec-round1.md` as a regression test; it sends mail to an
in-memory recorder so it never depends on Mailpit.
"""

from __future__ import annotations

import io
import random
import secrets
import statistics
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from matchdesk.core import RecordingMailer, configure_logging, load_settings
from matchdesk.identity import AuthError, SessionRow, User, code_at_step, enroll_operator, hash_token, step_at
from matchdesk.identity.auth import exchange_login_token, request_login_link
from matchdesk.tenancy import global_session

from .b2_helpers import (
    client,
    delete_messages_to,
    latest_token,
    messages_to,
    needs_mailpit,
    wait_for_messages,
)
from .seed import add_invoice, auth_headers, make_tenant

pytestmark = pytest.mark.integration


def email_of(engine, user_id) -> str:  # type: ignore[no-untyped-def]
    with global_session(engine) as s:
        return str(s.scalar(select(User.email).where(User.id == user_id)))


@pytest.fixture
def cleanup_mail():  # type: ignore[no-untyped-def]
    addresses: list[str] = []
    yield addresses
    delete_messages_to(*addresses)


def sign_in(c, address: str, cleanup: list[str]) -> dict:  # type: ignore[no-untyped-def]
    cleanup.append(address)
    before = len(messages_to(address))
    r = c.post("/api/v1/auth/login-links", json={"email": address})
    assert r.status_code == 202, r.text
    token = latest_token(address, count=before + 1)
    r = c.post("/api/v1/auth/sessions", json={"token": token})
    assert r.status_code == 201, r.text
    return r.json()


@needs_mailpit
def test_sign_in_end_to_end_cookie_csrf_reuse_and_logout(app_engine, cleanup_mail):  # type: ignore[no-untyped-def]
    log_stream = io.StringIO()
    configure_logging("INFO", log_stream)
    w = make_tenant(app_engine, "B2 sign-in")
    address = email_of(app_engine, w.user_id)
    cleanup_mail.append(address)
    browser = client()
    r = browser.post("/api/v1/auth/login-links", json={"email": address})
    assert r.status_code == 202
    binding = r.headers["set-cookie"]
    assert "__Host-md_signin=" in binding and "HttpOnly" in binding and "Secure" in binding
    token = latest_token(address)
    body = browser.post("/api/v1/auth/sessions", json={"token": token})
    assert body.status_code == 201, body.text
    cookie = next(c for c in body.headers.get_list("set-cookie") if c.startswith("__Host-md_session="))
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert attribute in cookie, attribute
    assert "Domain" not in cookie and "Max-Age" not in cookie  # a browser-session cookie
    data = body.json()
    assert data["active_tenant_id"] == str(w.tenant_id) and data["role"] == "clerk"
    csrf = data["csrf_token"]
    session_token = browser.cookies.get("__Host-md_session")
    assert session_token and session_token != token  # a new session token, not the link token

    me = browser.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == address
    # Mutating requests need the anti-forgery token.
    assert browser.post("/api/v1/auth/session/extend").status_code == 403
    assert browser.post("/api/v1/auth/session/extend", headers={"X-CSRF-Token": "x" * 43}).status_code == 403
    assert browser.post("/api/v1/auth/session/extend", headers={"X-CSRF-Token": csrf}).status_code == 200
    # A bearer token is not a session any more (B1 fake auth removed).
    anon = client()
    assert anon.get("/api/v1/me", headers={"Authorization": f"Bearer {session_token}"}).status_code == 401

    # The link works once.
    again = browser.post("/api/v1/auth/sessions", json={"token": token})
    assert again.status_code == 400

    # Logout ends the session on the server: replaying the old cookie is refused.
    out = browser.delete("/api/v1/auth/session", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 204
    replay = client()
    assert (
        replay.get("/api/v1/me", headers={"Cookie": f"__Host-md_session={session_token}"}).status_code == 401
    )

    logs = log_stream.getvalue()
    assert token not in logs and session_token not in logs and csrf not in logs and address not in logs


@needs_mailpit
def test_link_from_another_browser_is_refused_and_not_consumed(app_engine, cleanup_mail):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "B2 other browser")
    address = email_of(app_engine, w.user_id)
    cleanup_mail.append(address)
    requester, other = client(), client()
    requester.post("/api/v1/auth/login-links", json={"email": address})
    token = latest_token(address)
    refused = other.post("/api/v1/auth/sessions", json={"token": token})
    assert refused.status_code == 409 and "another browser" in refused.json()["detail"]
    assert requester.post("/api/v1/auth/sessions", json={"token": token}).status_code == 201


@needs_mailpit
def test_expired_link_is_refused(app_engine, cleanup_mail):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "B2 expired")
    address = email_of(app_engine, w.user_id)
    cleanup_mail.append(address)
    browser = client()
    browser.post("/api/v1/auth/login-links", json={"email": address})
    token = latest_token(address)
    with global_session(app_engine) as s:  # the link was issued 11 minutes ago
        s.execute(
            text(
                "update login_tokens set created_at = created_at - interval '11 minutes', "
                "expires_at = expires_at - interval '11 minutes' where user_id = :u"
            ),
            {"u": str(w.user_id)},
        )
    assert browser.post("/api/v1/auth/sessions", json={"token": token}).status_code == 400


@needs_mailpit
def test_unknown_address_gets_the_same_answer_and_no_mail(app_engine, cleanup_mail):  # type: ignore[no-untyped-def]
    known = make_tenant(app_engine, "B2 known")
    known_addr = email_of(app_engine, known.user_id)
    unknown = f"nobody-{uuid.uuid4().hex[:8]}@example.invalid"
    cleanup_mail.extend([known_addr, unknown])
    a = client().post("/api/v1/auth/login-links", json={"email": known_addr})
    b = client().post("/api/v1/auth/login-links", json={"email": unknown})
    assert (a.status_code, a.json()) == (b.status_code, b.json())
    assert len(wait_for_messages(known_addr)) == 1
    assert messages_to(unknown) == []


@needs_mailpit
def test_rate_limits_address_ip_and_failed_exchanges(app_engine, cleanup_mail):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "B2 rate limit")
    address = email_of(app_engine, w.user_id)
    cleanup_mail.append(address)
    # Per address: 5 links in 15 minutes; the sixth gets the same public answer and no mail.
    answers = [client().post("/api/v1/auth/login-links", json={"email": address}) for _ in range(6)]
    assert {r.status_code for r in answers} == {202}
    assert len({r.text for r in answers}) == 1
    assert len(wait_for_messages(address, count=6, timeout=2)) == 5
    # Per IP: 20 requests an hour, then 429 (says nothing about any address).
    browser = client()
    codes = [
        browser.post("/api/v1/auth/login-links", json={"email": f"x{i}@example.invalid"}).status_code
        for i in range(21)
    ]
    assert codes[:20] == [202] * 20 and codes[20] == 429
    # Failed exchanges: 10 per IP an hour, then 429 even for a token that would be valid.
    guesser = client()
    fails = [
        guesser.post("/api/v1/auth/sessions", json={"token": f"guess-{i:02d}-" + "x" * 30}).status_code
        for i in range(11)
    ]
    assert fails[:10] == [400] * 10 and fails[10] == 429


@needs_mailpit
def test_cross_tenant_session_is_refused(app_engine, cleanup_mail):  # type: ignore[no-untyped-def]
    a = make_tenant(app_engine, "B2 tenant A")
    b = make_tenant(app_engine, "B2 tenant B")
    add_invoice(app_engine, b, "b1", "INV-B1", datetime(2026, 10, 1, tzinfo=UTC).date(), "5")
    browser = client()
    data = sign_in(browser, email_of(app_engine, a.user_id), cleanup_mail)
    csrf = data["csrf_token"]
    # B's invoice reads as not found, exactly like a missing one.
    assert browser.get(f"/api/v1/invoices/{b.invoices['b1']}").status_code == 404
    assert browser.get(f"/api/v1/invoices/{uuid.uuid4()}").status_code == 404
    # Switching to a tenant without a membership is refused as not found.
    switch = browser.put(
        "/api/v1/me/active-tenant", json={"tenant_id": str(b.tenant_id)}, headers={"X-CSRF-Token": csrf}
    )
    assert switch.status_code == 404
    # Another session's anti-forgery token does not work with this cookie.
    assert (
        browser.post(
            "/api/v1/auth/session/extend", headers={"X-CSRF-Token": b.headers["X-CSRF-Token"]}
        ).status_code
        == 403
    )
    # A cross-site form post to a public endpoint is refused by origin.
    evil = client().post(
        "/api/v1/auth/login-links",
        json={"email": "a@example.invalid"},
        headers={"Origin": "https://evil.example"},
    )
    assert evil.status_code == 403


@needs_mailpit
def test_idle_and_absolute_limits(app_engine, cleanup_mail):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "B2 timeouts")
    browser = client()
    csrf = sign_in(browser, email_of(app_engine, w.user_id), cleanup_mail)["csrf_token"]
    token = browser.cookies.get("__Host-md_session")

    def age(column: str, minutes: int) -> None:
        with global_session(app_engine) as s:
            s.execute(
                text(f"update sessions set {column} = now() - make_interval(mins => :m) where user_id = :u"),  # noqa: S608
                {"m": minutes, "u": str(w.user_id)},
            )

    age("last_seen_at", 58)  # idle 58 minutes, then "Stay signed in"
    ext = browser.post("/api/v1/auth/session/extend", headers={"X-CSRF-Token": csrf})
    assert ext.status_code == 200
    assert datetime.fromisoformat(ext.json()["idle_expires_at"]) > datetime.now(UTC) + timedelta(minutes=59)
    age("last_seen_at", 61)  # idle 61 minutes: ended for good
    assert browser.get("/api/v1/me").status_code == 401
    with global_session(app_engine) as s:  # the row itself is gone
        assert s.scalar(select(SessionRow).where(SessionRow.token_hash == hash_token(str(token)))) is None

    # Absolute lifetime: 24 hours after sign-in, even when active.
    browser2 = client()
    sign_in(browser2, email_of(app_engine, w.user_id), cleanup_mail)
    with global_session(app_engine) as s:
        s.execute(
            text("update sessions set expires_at = now() - interval '1 second' where user_id = :u"),
            {"u": str(w.user_id)},
        )
    assert browser2.get("/api/v1/me").status_code == 401
    assert token is not None


@needs_mailpit
def test_operator_needs_a_one_time_code_used_once(app_engine, cleanup_mail):  # type: ignore[no-untyped-def]
    address = f"operator-{uuid.uuid4().hex[:8]}@example.invalid"
    cleanup_mail.append(address)
    with global_session(app_engine) as s:
        s.add(User(email=address, display_name="Synthetic operator"))
    secret = enroll_operator(app_engine, address)
    browser = client()
    browser.post("/api/v1/auth/login-links", json={"email": address})
    token = latest_token(address)
    without = browser.post("/api/v1/auth/sessions", json={"token": token})
    assert without.status_code == 401 and "authenticator" in without.json()["detail"]
    wrong = browser.post("/api/v1/auth/sessions", json={"token": token, "totp_code": "000000"})
    if wrong.status_code == 201:  # one chance in a million that 000000 is the current code
        pytest.skip("random code collision")
    assert wrong.status_code == 401
    code = code_at_step(secret, step_at(datetime.now(UTC)))
    ok = browser.post("/api/v1/auth/sessions", json={"token": token, "totp_code": code})
    assert ok.status_code == 201, ok.text
    me = ok.json()
    assert me["user"]["is_operator"] is True and me["active_tenant_id"] is None
    # Without a tenant, tenant data is not found.
    assert browser.get(f"/api/v1/invoices/{uuid.uuid4()}").status_code == 404
    # The same code cannot be used again with a fresh link.
    before = len(messages_to(address))
    browser.post("/api/v1/auth/login-links", json={"email": address})
    token2 = latest_token(address, count=before + 1)
    reused = browser.post("/api/v1/auth/sessions", json={"token": token2, "totp_code": code})
    assert reused.status_code == 401
    with global_session(app_engine) as s:
        sealed = s.scalar(select(User.totp_secret_enc).where(User.email == address))
    assert sealed is not None and secret not in sealed


@needs_mailpit
def test_invitation_roles_last_controller_and_deactivation(app_engine, cleanup_mail):  # type: ignore[no-untyped-def]
    boss = make_tenant(app_engine, "B2 invitations", role="controller")
    browser = client()
    csrf = sign_in(browser, email_of(app_engine, boss.user_id), cleanup_mail)["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    invitee = f"invitee-{uuid.uuid4().hex[:8]}@example.invalid"
    cleanup_mail.append(invitee)
    r = browser.post("/api/v1/invitations", json={"email": invitee, "role": "viewer"}, headers=h)
    assert r.status_code == 201, r.text
    inv_id = r.json()["id"]
    assert [i["id"] for i in browser.get("/api/v1/invitations").json()["items"]] == [inv_id]
    token = latest_token(invitee, path="/invite")

    guest = client()
    accepted = guest.post("/api/v1/invitations/accept", json={"token": token})
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["role"] == "viewer" and accepted.json()["active_tenant_id"] == str(boss.tenant_id)
    guest_csrf = accepted.json()["csrf_token"]
    assert client().post("/api/v1/invitations/accept", json={"token": token}).status_code == 400  # once only
    # A viewer cannot invite, list users or start a match run (403 inside the own tenant).
    gh = {"X-CSRF-Token": guest_csrf}
    assert (
        guest.post(
            "/api/v1/invitations", json={"email": "z@example.invalid", "role": "clerk"}, headers=gh
        ).status_code
        == 403
    )
    assert guest.get("/api/v1/users").status_code == 403
    assert (
        guest.post("/api/v1/match-runs", json={"invoice_ids": [str(uuid.uuid4())]}, headers=gh).status_code
        == 403
    )

    # A revoked invitation cannot be accepted.
    second = f"second-{uuid.uuid4().hex[:8]}@example.invalid"
    cleanup_mail.append(second)
    r2 = browser.post("/api/v1/invitations", json={"email": second, "role": "clerk"}, headers=h)
    token2 = latest_token(second, path="/invite")
    assert browser.delete(f"/api/v1/invitations/{r2.json()['id']}", headers=h).status_code == 204
    assert client().post("/api/v1/invitations/accept", json={"token": token2}).status_code == 400

    users = {u["email"]: u for u in browser.get("/api/v1/users").json()["items"]}
    own = users[email_of(app_engine, boss.user_id)]["membership_id"]
    guest_m = users[invitee]["membership_id"]
    # Nobody changes their own membership; the last controller cannot be removed.
    assert browser.patch(f"/api/v1/memberships/{own}", json={"role": "clerk"}, headers=h).status_code == 403
    with pytest.raises(Exception, match="last active controller"):
        from matchdesk.tenancy import session

        with session(boss.tenant_id, app_engine) as s:
            s.execute(text("update memberships set role = 'clerk' where id = :m"), {"m": own})
    # Deactivation ends the user's sessions in this tenant at once.
    assert guest.get("/api/v1/me").status_code == 200
    d = browser.patch(f"/api/v1/memberships/{guest_m}", json={"status": "deactivated"}, headers=h)
    assert d.status_code == 200 and d.json()["status"] == "deactivated"
    assert guest.get("/api/v1/me").status_code == 401
    # The audit log holds the sign-in, invitation and membership events.
    from matchdesk.tenancy import session as tsession

    with tsession(boss.tenant_id, app_engine) as s:
        actions = set(s.scalars(text("select action from audit_events")).all())
    assert {
        "sign_in",
        "invitation_created",
        "invitation_accepted",
        "invitation_revoked",
        "membership_changed",
    } <= actions


# ------------------------------------------------------------------ security fixes after B2 review, round 1


def _browser(mailer=None, ip=None, raise_errors=True):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from matchdesk.api.app import create_app

    from .b2_helpers import BASE_URL

    addr = ip or f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
    return TestClient(
        create_app(mailer=mailer or RecordingMailer()),
        base_url=BASE_URL,
        client=(addr, 50000),
        raise_server_exceptions=raise_errors,
    )


def _token(body: str, path: str = "/login/verify") -> str:
    from .b2_helpers import token_from

    return token_from(body, path)


def _operator(engine):  # type: ignore[no-untyped-def]
    address = f"op-{uuid.uuid4().hex[:8]}@example.invalid"
    with global_session(engine) as s:
        s.add(User(email=address, display_name="Synthetic operator"))
    return address, enroll_operator(engine, address)


def _wrong(secret: bytes) -> str:
    now = step_at(datetime.now(UTC))
    valid = {code_at_step(secret, st) for st in range(now - 3, now + 4)}
    while True:
        c = f"{random.randint(0, 999999):06d}"
        if c not in valid:
            return c


def _signed_in(engine, address: str):  # type: ignore[no-untyped-def]
    rec = RecordingMailer()
    b = _browser(rec)
    assert b.post("/api/v1/auth/login-links", json={"email": address}).status_code == 202
    r = b.post("/api/v1/auth/sessions", json={"token": _token(rec.sent[-1].body)})
    assert r.status_code == 201, r.text
    return b, r.json()


def test_b2_s01_operator_cannot_enter_a_tenant_through_an_invitation(app_engine):  # type: ignore[no-untyped-def]
    op_addr, _secret = _operator(app_engine)
    boss = make_tenant(app_engine, "sec s01", role="controller")
    rec = RecordingMailer()
    ctl = _browser(rec)
    assert (
        ctl.post(
            "/api/v1/invitations", json={"email": op_addr, "role": "viewer"}, headers=boss.headers
        ).status_code
        == 201
    )
    attacker = _browser()  # holds only the mailbox, no authenticator
    acc = attacker.post("/api/v1/invitations/accept", json={"token": _token(rec.sent[-1].body, "/invite")})
    assert acc.status_code == 409
    assert attacker.get("/api/v1/me").status_code == 401
    # Data layer: an operator's session never carries a tenant, even if one is forced in.
    inv = add_invoice(app_engine, boss, "o1", "INV-O1", datetime(2026, 10, 1, tzinfo=UTC).date(), "5")
    with global_session(app_engine) as s:
        op_id = s.scalar(select(User.id).where(User.email == op_addr))
    from matchdesk.identity import issue_session, load_session

    tok = issue_session(app_engine, op_id, boss.tenant_id)
    ctx = load_session(app_engine, tok)
    assert ctx is not None and ctx.tenant_id is None and ctx.principal() is None
    assert _browser().get(f"/api/v1/invoices/{inv}", headers=auth_headers(tok)).status_code == 404
    with (
        pytest.raises(Exception, match="operator session cannot carry a tenant"),
        global_session(app_engine) as s,
    ):
        s.execute(
            text("update sessions set active_tenant_id = :t where user_id = :u"),
            {"t": str(boss.tenant_id), "u": str(op_id)},
        )
    # A member who later becomes an operator loses the sessions opened before.
    member_tok = boss.token
    assert _browser().get("/api/v1/me", headers=boss.headers).status_code == 200
    enroll_operator(app_engine, email_of(app_engine, boss.user_id))
    assert _browser().get("/api/v1/me", headers=auth_headers(member_tok)).status_code == 401


def test_b2_s02_wrong_codes_are_limited_per_link_and_per_account(app_engine):  # type: ignore[no-untyped-def]
    op_addr, secret = _operator(app_engine)
    rec = RecordingMailer()
    b = _browser(rec)
    b.post("/api/v1/auth/login-links", json={"email": op_addr})
    tok = _token(rec.sent[-1].body)
    binding = b.cookies.get("__Host-md_signin")
    statuses = []
    for _ in range(40):  # 40 guesses from 40 IP addresses, one link
        r = _browser().post(
            "/api/v1/auth/sessions",
            json={"token": tok, "totp_code": _wrong(secret)},
            headers={"Cookie": f"__Host-md_signin={binding}"},
        )
        statuses.append(r.status_code)
    assert statuses[:3] == [401, 401, 401] and set(statuses[3:]) == {400}  # burned after 3
    good = code_at_step(secret, step_at(datetime.now(UTC)))
    final = _browser().post(
        "/api/v1/auth/sessions",
        json={"token": tok, "totp_code": good},
        headers={"Cookie": f"__Host-md_signin={binding}"},
    )
    assert final.status_code == 400
    # Per account: two more links, two wrong codes each, from fresh IPs: the fifth failure burns
    # every open link and the account answers 429 for the window, even with the right code.
    tokens = []
    for _ in range(2):
        b.post("/api/v1/auth/login-links", json={"email": op_addr})
        tokens.append(_token(rec.sent[-1].body))
    results = [
        _browser()
        .post(
            "/api/v1/auth/sessions",
            json={"token": t, "totp_code": _wrong(secret)},
            headers={"Cookie": f"__Host-md_signin={binding}"},
        )
        .status_code
        for t in tokens
    ]
    assert results == [401, 401]  # failures 4 and 5
    b.post("/api/v1/auth/login-links", json={"email": op_addr})
    fresh = _token(rec.sent[-1].body)
    locked = _browser().post(
        "/api/v1/auth/sessions",
        json={"token": fresh, "totp_code": good},
        headers={"Cookie": f"__Host-md_signin={binding}"},
    )
    assert locked.status_code == 429
    with global_session(app_engine) as s:
        open_links = s.execute(
            text(
                "select count(*) from login_tokens t join users u on u.id = t.user_id "
                "where u.email = :e and t.used_at is null"
            ),
            {"e": op_addr},
        ).scalar()
    assert open_links == 0


def test_b2_s03_one_totp_step_signs_in_once_under_concurrency(app_engine):  # type: ignore[no-untyped-def]
    op_addr, secret = _operator(app_engine)
    cfg = load_settings()
    base = datetime.now(UTC) + timedelta(days=1)
    double = 0
    for k in range(8):
        at = base + timedelta(minutes=16 * k)
        binding = secrets.token_urlsafe(32)
        toks = []
        for _ in range(2):
            mail = request_login_link(app_engine, op_addr, None, binding, cfg, now=at)
            assert mail is not None
            toks.append(_token(mail.body))
        code = code_at_step(secret, step_at(at))
        gate = threading.Barrier(2)
        wins: list[bool] = []

        def go(
            t: str,
            code: str = code,
            at: datetime = at,
            binding: str = binding,
            gate: threading.Barrier = gate,
            wins: list[bool] = wins,
        ) -> None:
            gate.wait()
            try:
                exchange_login_token(app_engine, t, binding, None, code, cfg, now=at)
                wins.append(True)
            except AuthError:
                wins.append(False)

        threads = [threading.Thread(target=go, args=(t,)) for t in toks]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        double += wins.count(True) == 2
    assert double == 0


def test_b2_s04_link_limit_holds_for_parallel_requests(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "sec s04")
    addr = email_of(app_engine, w.user_id)
    cfg = load_settings()
    at = datetime.now(UTC) + timedelta(days=3)
    gate = threading.Barrier(20)
    sent: list[bool] = []

    def go() -> None:
        gate.wait()
        sent.append(
            request_login_link(app_engine, addr, None, secrets.token_urlsafe(32), cfg, now=at) is not None
        )

    threads = [threading.Thread(target=go) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sent.count(True) == 5


def test_b2_s06_deactivation_revokes_invitations_and_no_invitation_reactivates(app_engine):  # type: ignore[no-untyped-def]
    boss = make_tenant(app_engine, "sec s06", role="controller")
    rec = RecordingMailer()
    ctl = _browser(rec)
    x = f"x-{uuid.uuid4().hex[:8]}@example.invalid"
    for _ in range(2):  # "resend invitation"
        assert (
            ctl.post(
                "/api/v1/invitations", json={"email": x, "role": "clerk"}, headers=boss.headers
            ).status_code
            == 201
        )
    t1, t2 = (_token(m.body, "/invite") for m in rec.sent[-2:])
    member = _browser()
    assert member.post("/api/v1/invitations/accept", json={"token": t1}).status_code == 201
    users = {u["email"]: u for u in ctl.get("/api/v1/users", headers=boss.headers).json()["items"]}
    mid = users[x]["membership_id"]
    assert (
        ctl.patch(
            f"/api/v1/memberships/{mid}", json={"status": "deactivated"}, headers=boss.headers
        ).status_code
        == 200
    )
    # The older open invitation was revoked with the membership, and the session ended.
    assert ctl.get("/api/v1/invitations", headers=boss.headers).json()["items"] == []
    assert member.get("/api/v1/me").status_code == 401
    assert _browser().post("/api/v1/invitations/accept", json={"token": t2}).status_code == 400
    # A fresh invitation sent after the deactivation does not re-activate either.
    ctl.post("/api/v1/invitations", json={"email": x, "role": "controller"}, headers=boss.headers)
    t3 = _token(rec.sent[-1].body, "/invite")
    assert _browser().post("/api/v1/invitations/accept", json={"token": t3}).status_code == 400
    users = {u["email"]: u for u in ctl.get("/api/v1/users", headers=boss.headers).json()["items"]}
    assert (users[x]["status"], users[x]["role"]) == ("deactivated", "clerk")
    # Only a controller re-activates.
    back = ctl.patch(f"/api/v1/memberships/{mid}", json={"status": "active"}, headers=boss.headers)
    assert back.status_code == 200 and back.json()["status"] == "active"


def test_b2_s07_sessions_end_when_the_tenant_ends(app_engine, owner_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "sec s07")
    inv = add_invoice(app_engine, w, "e1", "INV-E1", datetime(2026, 10, 1, tzinfo=UTC).date(), "5")
    c = _browser()
    assert c.get(f"/api/v1/invoices/{inv}", headers=w.headers).status_code == 200
    with owner_engine.begin() as conn:
        conn.execute(text("update tenants set status = 'ended' where id = :t"), {"t": str(w.tenant_id)})
    assert c.get(f"/api/v1/invoices/{inv}", headers=w.headers).status_code == 401
    with global_session(app_engine) as s:
        assert s.scalar(select(SessionRow).where(SessionRow.token_hash == hash_token(w.token))) is None


def test_b2_s15_non_ascii_code_is_a_clean_refusal(app_engine):  # type: ignore[no-untyped-def]
    op_addr, _secret = _operator(app_engine)
    rec = RecordingMailer()
    b = _browser(rec, raise_errors=False)
    b.post("/api/v1/auth/login-links", json={"email": op_addr})
    r = b.post(
        "/api/v1/auth/sessions",
        json={"token": _token(rec.sent[-1].body), "totp_code": "\uff11\uff12\uff13\uff14\uff15\uff16"},
    )
    assert r.status_code == 401


def test_b2_s16_link_requests_take_the_same_time_for_known_and_unknown(app_engine):  # type: ignore[no-untyped-def]
    cfg = load_settings()
    worlds = [make_tenant(app_engine, f"sec s16 t{i}") for i in range(30)]
    addrs = [email_of(app_engine, w.user_id) for w in worlds]
    kn: list[int] = []
    un: list[int] = []
    for i in range(30):
        for kind in ("k", "u") if i % 2 else ("u", "k"):
            a = addrs[i] if kind == "k" else f"nobody-{uuid.uuid4().hex[:8]}@example.invalid"
            t0 = time.perf_counter_ns()
            request_login_link(app_engine, a, None, secrets.token_urlsafe(32), cfg)
            (kn if kind == "k" else un).append(time.perf_counter_ns() - t0)
    mk, mu = statistics.median(kn), statistics.median(un)
    cut = (mk + mu) / 2
    correct = sum(x > cut for x in kn) + sum(x <= cut for x in un)
    assert correct * 4 < (len(kn) + len(un)) * 3  # a midpoint classifier is right under 75%


def test_b2_s18_no_ip_at_rest_and_rate_keys_are_keyed(app_engine):  # type: ignore[no-untyped-def]
    import hashlib

    w = make_tenant(app_engine, "sec s18")
    ip = "10.77.88.99"
    _browser(ip=ip).post("/api/v1/auth/login-links", json={"email": email_of(app_engine, w.user_id)})
    with global_session(app_engine) as s:
        raw = s.scalar(
            text("select count(*) from login_tokens where user_id = :u and requested_ip is not null"),
            {"u": str(w.user_id)},
        )
        rev = s.scalar(
            text("select count(*) from auth_rate_events where key_hash = :h"),
            {"h": hashlib.sha256(f"link_ip:{ip}".encode()).digest()},
        )
        issued = s.scalar(text("select count(*) from login_tokens where user_id = :u"), {"u": str(w.user_id)})
    assert issued == 1 and raw == 0 and rev == 0


# Mutations M1 to M6 of the review: each control below fails a test when it is removed (B2-S08).


def test_b2_m1_m2_clerk_cannot_change_memberships_or_revoke_invitations(app_engine):  # type: ignore[no-untyped-def]
    boss = make_tenant(app_engine, "sec m1", role="controller")
    rec = RecordingMailer()
    ctl = _browser(rec)
    r = ctl.post(
        "/api/v1/invitations",
        json={"email": f"m-{uuid.uuid4().hex[:6]}@example.invalid", "role": "clerk"},
        headers=boss.headers,
    )
    inv_id = r.json()["id"]
    clerk = _browser()
    acc = clerk.post("/api/v1/invitations/accept", json={"token": _token(rec.sent[-1].body, "/invite")})
    ch = {"X-CSRF-Token": acc.json()["csrf_token"]}
    users = {u["role"]: u for u in ctl.get("/api/v1/users", headers=boss.headers).json()["items"]}
    boss_m = users["controller"]["membership_id"]
    assert (
        clerk.patch(f"/api/v1/memberships/{boss_m}", json={"role": "viewer"}, headers=ch).status_code == 403
    )
    r2 = ctl.post(
        "/api/v1/invitations",
        json={"email": f"n-{uuid.uuid4().hex[:6]}@example.invalid", "role": "viewer"},
        headers=boss.headers,
    )
    assert clerk.delete(f"/api/v1/invitations/{r2.json()['id']}", headers=ch).status_code == 403
    assert [i["id"] for i in ctl.get("/api/v1/invitations", headers=boss.headers).json()["items"]] == [
        r2.json()["id"]
    ]
    assert inv_id != r2.json()["id"]


def test_b2_m3_expired_invitation_is_refused(app_engine):  # type: ignore[no-untyped-def]
    from matchdesk.tenancy import session as tsession

    boss = make_tenant(app_engine, "sec m3", role="controller")
    rec = RecordingMailer()
    r = _browser(rec).post(
        "/api/v1/invitations",
        json={"email": f"e-{uuid.uuid4().hex[:6]}@example.invalid", "role": "clerk"},
        headers=boss.headers,
    )
    tok = _token(rec.sent[-1].body, "/invite")
    with tsession(boss.tenant_id, app_engine) as s:
        s.execute(
            text("update invitations set expires_at = now() - interval '1 second' where id = :i"),
            {"i": r.json()["id"]},
        )
    assert _browser().post("/api/v1/invitations/accept", json={"token": tok}).status_code == 400


def test_b2_m4_signing_in_again_ends_the_browser_s_previous_session(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "sec m4")
    addr = email_of(app_engine, w.user_id)
    b, _data = _signed_in(app_engine, addr)
    old = b.cookies.get("__Host-md_session")
    rec = RecordingMailer()
    again = _browser(rec)
    again.post("/api/v1/auth/login-links", json={"email": addr})
    bnd = again.cookies.get("__Host-md_signin")
    r = again.post(
        "/api/v1/auth/sessions",
        json={"token": _token(rec.sent[-1].body)},
        headers={"Cookie": f"__Host-md_session={old}; __Host-md_signin={bnd}"},
    )
    assert r.status_code == 201
    assert _browser().get("/api/v1/me", headers={"Cookie": f"__Host-md_session={old}"}).status_code == 401


def test_b2_m5_deactivated_user_is_refused_on_the_next_request(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "sec m5")
    assert _browser().get("/api/v1/me", headers=w.headers).status_code == 200
    with global_session(app_engine) as s:
        s.execute(text("update users set deactivated_at = now() where id = :u"), {"u": str(w.user_id)})
    assert _browser().get("/api/v1/me", headers=w.headers).status_code == 401


@pytest.mark.parametrize(
    "path", ["/api/v1/auth/login-links", "/api/v1/auth/sessions", "/api/v1/invitations/accept"]
)
def test_b2_m6_public_posts_refuse_a_foreign_origin(app_engine, path):  # type: ignore[no-untyped-def]
    body = {"email": "a@example.invalid"} if path.endswith("login-links") else {"token": "x" * 43}
    r = _browser().post(path, json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["title"] == "Cross-site request refused"
