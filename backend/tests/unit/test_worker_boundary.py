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
