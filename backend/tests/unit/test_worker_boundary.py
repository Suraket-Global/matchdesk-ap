"""IT-16b: the worker starts and processes with web-only packages made unimportable (R-07)."""

from __future__ import annotations

import subprocess
import sys

CODE = """
import sys
for name in ("fastapi", "starlette", "uvicorn"):
    sys.modules[name] = None
import matchdesk.worker.__main__ as w
assert "fastapi" not in [m for m in sys.modules if sys.modules[m] is not None]
print("worker-import-ok", sorted(w.handlers(None)))
"""


def test_it16b_worker_imports_without_web_framework():
    res = subprocess.run([sys.executable, "-c", CODE], check=False, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "worker-import-ok" in res.stdout


MODELS = """
import matchdesk.worker.__main__  # noqa: F401
from matchdesk.tenancy.db import Base
from sqlalchemy.orm import configure_mappers
configure_mappers()
assert {"tenants", "users", "extraction_runs", "documents"} <= set(Base.metadata.tables)
for t in Base.metadata.sorted_tables:
    for fk in t.foreign_keys:
        fk.column  # raises NoReferencedTableError when a target model was never imported
print("models-ok")
"""


def test_worker_registers_every_model_before_its_first_flush():
    """B4 regression: a standalone worker failed every document job with NoReferencedTableError."""
    res = subprocess.run([sys.executable, "-c", MODELS], check=False, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "models-ok" in res.stdout
