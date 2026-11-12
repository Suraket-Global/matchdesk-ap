"""B6, outside QA finding 2: a seed run touches only the tenant it creates.

``seed_demo.py --tag`` (what Playwright runs, now against its own database) used to delete every
row of ``auth_rate_events``. It must leave other tenants and the sign-in counters alone.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text

from tests.integration.conftest import APP_URL, OWNER_URL

ROOT = Path(__file__).resolve().parents[2]


def _counts(owner_engine) -> dict[str, int]:  # type: ignore[no-untyped-def]
    with owner_engine.connect() as c:
        return {
            t: int(c.execute(text(f'select count(*) from "{t}"')).scalar_one())  # noqa: S608
            for t in ("auth_rate_events", "tenants", "users", "memberships")
        }


def test_a_tagged_seed_keeps_rate_events_and_adds_only_its_own_tenant(owner_engine) -> None:  # type: ignore[no-untyped-def]
    with owner_engine.begin() as c:
        c.execute(
            text("insert into auth_rate_events (kind, key_hash) values ('link_address', :h)"),
            {"h": b"synthetic-other-address"},
        )
    before = _counts(owner_engine)
    env = {
        **os.environ,
        "MATCHDESK_DATABASE_URL": APP_URL,
        "MATCHDESK_MIGRATION_DATABASE_URL": OWNER_URL,
        "MATCHDESK_ENV": "dev",
    }
    with tempfile.TemporaryDirectory() as files:
        subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--tag", "isolation1", "--files-dir", files],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )
    after = _counts(owner_engine)
    assert after["auth_rate_events"] == before["auth_rate_events"]
    assert after["tenants"] == before["tenants"] + 1
    assert after["memberships"] == before["memberships"] + 2


def test_the_seed_script_deletes_nothing_outside_its_tenant() -> None:
    source = (ROOT / "scripts" / "seed_demo.py").read_text()
    assert "delete from" not in source.lower() and "truncate" not in source.lower()
