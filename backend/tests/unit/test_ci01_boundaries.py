"""CI-01: an import of ``api`` from ``matching`` breaks the boundary contract."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ci01_wrong_import_fails_contract(tmp_path):
    copy = tmp_path / "src"
    shutil.copytree(ROOT / "src", copy)
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    lint = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    assert lint
    env = {"PYTHONPATH": str(copy), "PATH": str(Path(sys.executable).parent)}
    ok = subprocess.run([lint], cwd=tmp_path, env=env, check=False, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    (copy / "matchdesk" / "matching" / "probe.py").write_text("import matchdesk.api.app\n")
    bad = subprocess.run(
        [lint, "--no-cache"], cwd=tmp_path, env=env, check=False, capture_output=True, text=True
    )
    assert bad.returncode != 0
    assert "BROKEN" in bad.stdout
