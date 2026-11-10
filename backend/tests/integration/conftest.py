"""Integration fixtures: a clean ``matchdesk_test`` database migrated from scratch.

Migrations and the reset run as the owner (the local OS superuser). Every test
query runs as ``matchdesk_app``, which is NOSUPERUSER NOBYPASSRLS, so row-level
security is really exercised.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
OWNER_URL = os.environ.get(
    "MATCHDESK_TEST_OWNER_URL", "postgresql+psycopg://zakria@localhost:5432/matchdesk_test"
)
APP_URL = os.environ.get(
    "MATCHDESK_TEST_APP_URL", "postgresql+psycopg://matchdesk_app@localhost:5432/matchdesk_test"
)

# Set before any app or engine is created; module-scoped fixtures build apps too.
os.environ["MATCHDESK_DATABASE_URL"] = APP_URL
os.environ["MATCHDESK_BLOB_ROOT"] = tempfile.mkdtemp(prefix="matchdesk-test-blobs-")


@pytest.fixture(scope="session")
def migrated() -> None:
    owner = create_engine(OWNER_URL, isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        c.execute(text("drop schema if exists public cascade"))
        c.execute(text("create schema public"))
        c.execute(text("grant usage on schema public to public"))
    owner.dispose()
    env = {**os.environ, "MATCHDESK_MIGRATION_DATABASE_URL": OWNER_URL}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def app_engine(migrated: None):  # type: ignore[no-untyped-def]
    eng = create_engine(APP_URL, future=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def owner_engine(migrated: None):  # type: ignore[no-untyped-def]
    eng = create_engine(OWNER_URL, future=True)
    yield eng
    eng.dispose()
