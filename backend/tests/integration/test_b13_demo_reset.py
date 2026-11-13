"""B13: ``make demo-reset`` rebuilds the demo tenant only (the B6 rule: a seed script touches only its
own tenant). A sandbox account in Intuit mode keeps its QuickBooks connection and sealed tokens.

Runs ``scripts/demo_tenant_reset.py`` and ``scripts/seed_demo.py`` as subprocesses against
``matchdesk_test``, as ``demo_reset.sh`` runs them against ``matchdesk_dev``."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select, text

from matchdesk.identity import Membership, Tenant, User
from matchdesk.qbo.models import QboConnection
from matchdesk.tenancy import global_session, session
from tests.integration.conftest import APP_URL, OWNER_URL

ROOT = Path(__file__).resolve().parents[2]
DEMO = "Demo Distributor Ltd (synthetic)"
ENV = {
    **os.environ,
    "MATCHDESK_DATABASE_URL": APP_URL,
    "MATCHDESK_MIGRATION_DATABASE_URL": OWNER_URL,
    "MATCHDESK_ENV": "dev",
}


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args], check=False, cwd=ROOT, env=ENV, capture_output=True, text=True
    )


def seed(tag: str) -> None:
    with tempfile.TemporaryDirectory() as files:
        r = run("scripts/seed_demo.py", "--tag", tag, "--files-dir", files, "--preload")
    assert r.returncode == 0, r.stderr[-2000:]


def sandbox(engine) -> tuple[uuid.UUID, bytes]:  # type: ignore[no-untyped-def]
    with global_session(engine) as s:
        t = Tenant(name=f"Fictional Sandbox CA {uuid.uuid4().hex[:6]}", qbo_mode="intuit", currency="CAD")
        u = User(email=f"{uuid.uuid4().hex[:8]}@example.invalid", display_name="Synthetic controller")
        s.add_all([t, u])
        s.flush()
        tid, uid = t.id, u.id
    sealed = b"sealed-token-invented-" + uuid.uuid4().bytes
    with session(tid, engine) as s:
        s.add(Membership(tenant_id=tid, user_id=uid, role="controller"))
        s.add(
            QboConnection(
                tenant_id=tid,
                realm_id=f"realm-invented-{tid}",
                company_name="Sandbox Company CA (invented)",
                refresh_token_enc=sealed,
                access_token_enc=sealed,
                token_key_id="k1",
                status="connected",
                connected_by=uid,
            )
        )
    return tid, sealed


def tenant_rows(owner_engine, tid: uuid.UUID) -> int:  # type: ignore[no-untyped-def]
    with owner_engine.connect() as c:
        tables = [
            r[0]
            for r in c.execute(
                text(
                    "select c.table_name from information_schema.columns c join information_schema.tables t "
                    "on t.table_name = c.table_name and t.table_schema = c.table_schema "
                    "where c.table_schema = 'public' and c.column_name = 'tenant_id' and t.table_type = 'BASE TABLE'"
                )
            )
        ]
        return sum(
            int(c.execute(text(f'select count(*) from "{t}" where tenant_id = :t'), {"t": tid}).scalar_one())  # noqa: S608
            for t in tables
        )


def test_demo_reset_keeps_a_sandbox_account_and_its_connection(app_engine, owner_engine) -> None:  # type: ignore[no-untyped-def]
    sandbox_id, sealed = sandbox(app_engine)
    before_sandbox = tenant_rows(owner_engine, sandbox_id)
    tag = f"reset{uuid.uuid4().hex[:6]}"
    seed(tag)
    with global_session(app_engine) as s:
        demo_id = s.scalar(select(Tenant.id).where(Tenant.name == f"{DEMO} {tag}"))
    assert demo_id is not None and tenant_rows(owner_engine, demo_id) > 50  # documents, audit, reports...
    r = run("scripts/demo_tenant_reset.py", "--name", f"{DEMO} {tag}")
    assert r.returncode == 0, r.stderr
    assert "other accounts untouched" in r.stdout
    with global_session(app_engine) as s:
        assert s.scalar(select(Tenant.id).where(Tenant.name == f"{DEMO} {tag}")) is None
        assert s.get(Tenant, sandbox_id) is not None
    assert tenant_rows(owner_engine, demo_id) == 0
    assert tenant_rows(owner_engine, sandbox_id) == before_sandbox
    with session(sandbox_id, app_engine) as s:
        conn = s.scalar(select(QboConnection))
        assert conn is not None and conn.status == "connected"
        assert conn.refresh_token_enc == sealed and conn.access_token_enc == sealed
    # The demo seeds again on the emptied name.
    seed(tag)
    with global_session(app_engine) as s:
        assert s.scalar(select(Tenant.id).where(Tenant.name == f"{DEMO} {tag}")) is not None


def test_demo_reset_refuses_an_intuit_account_and_other_names(app_engine, owner_engine) -> None:  # type: ignore[no-untyped-def]
    sandbox_id, _sealed = sandbox(app_engine)
    with global_session(app_engine) as s:
        t = s.get(Tenant, sandbox_id)
        assert t is not None
        name = t.name
        t.name = f"{DEMO} intuit{uuid.uuid4().hex[:6]}"
        renamed = t.name
    rows = tenant_rows(owner_engine, sandbox_id)
    refused = run("scripts/demo_tenant_reset.py", "--name", renamed)
    assert refused.returncode != 0 and "Intuit account" in (refused.stderr + refused.stdout)
    assert tenant_rows(owner_engine, sandbox_id) == rows
    other = run("scripts/demo_tenant_reset.py", "--name", name)
    assert other.returncode == 1 and "only a tenant named" in other.stderr
    wrong_db = subprocess.run(
        [sys.executable, "scripts/demo_tenant_reset.py"],
        check=False,
        cwd=ROOT,
        env={**ENV, "MATCHDESK_MIGRATION_DATABASE_URL": OWNER_URL.rsplit("/", 1)[0] + "/postgres"},
        capture_output=True,
        text=True,
    )
    assert wrong_db.returncode == 1 and "refused" in wrong_db.stderr


def test_demo_reset_script_wipes_no_database() -> None:
    source = (ROOT / "scripts" / "demo_reset.sh").read_text().lower()
    assert "drop schema" not in source and "demo_tenant_reset.py" in source
    assert "drop schema" in (ROOT / "scripts" / "dev_db_wipe.sh").read_text().lower()
