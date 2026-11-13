"""IT-08 (first half): one head, and a database built from migrations matches the ORM models."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from .conftest import OWNER_URL, ROOT

pytestmark = pytest.mark.integration


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "MATCHDESK_MIGRATION_DATABASE_URL": OWNER_URL}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_single_head(migrated):  # type: ignore[no-untyped-def]
    heads = [ln for ln in _alembic("heads").stdout.splitlines() if ln.strip()]
    assert len(heads) == 1 and heads[0].startswith("0025")


def test_orm_parity(migrated):  # type: ignore[no-untyped-def]
    res = _alembic("check")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "No new upgrade operations detected" in res.stdout + res.stderr
