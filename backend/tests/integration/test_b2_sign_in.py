"""B2 sign-in through the local Mailpit inbox (IT-18 subset, IT-13 subset; TRD 8.1; T-2.2.3).

Every link is read from Mailpit, never from the server's return values.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from matchdesk.core import configure_logging
from matchdesk.identity import SessionRow, User, code_at_step, enroll_operator, hash_token, step_at
from matchdesk.tenancy import global_session

from .b2_helpers import (
    client,
    delete_messages_to,
    latest_token,
    messages_to,
    needs_mailpit,
    wait_for_messages,
)
from .seed import add_invoice, make_tenant

pytestmark = [pytest.mark.integration, needs_mailpit]


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
