"""UT-09 and CI-04: Decimal money arithmetic, half-up rounding once, floats refused."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal as D
from pathlib import Path

import pytest

from matchdesk.core import FloatNotAllowedError, dec, line_amount, round_cents
from matchdesk.matching import MatchInput, input_fingerprint

ROOT = Path(__file__).resolve().parents[2]


def test_ut09_half_up_rounding_and_float_refused():
    assert line_amount(D("3"), D("0.335")) == D("1.01")  # 1.005 rounds half-up
    assert round_cents(D("2.675")) == D("2.68")
    with pytest.raises(FloatNotAllowedError):
        dec(0.335)  # type: ignore[arg-type]
    with pytest.raises(FloatNotAllowedError):
        line_amount(3, 0.335)  # type: ignore[arg-type]
    assert dec("4.20") == D("4.20")


def test_fingerprint_refuses_float():
    inp = MatchInput(
        tenant_currency="CAD",
        test_document_ids=frozenset(),
        documents=(),
        purchase_orders=(),
        ruleset_code=0.1,
    )  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        input_fingerprint(inp)


def test_ci04_float_lint_passes_on_tree_and_fails_on_bad_file(tmp_path):
    script = ROOT / "scripts" / "check_no_float.py"
    ok = subprocess.run([sys.executable, str(script)], cwd=ROOT, check=False, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = tmp_path / "bad.py"
    bad.write_text("x = 0.5\ny = float('1')\n")
    res = subprocess.run([sys.executable, str(script), str(bad)], check=False, capture_output=True, text=True)
    assert res.returncode == 1
    assert "float literal" in res.stdout and "float()" in res.stdout
