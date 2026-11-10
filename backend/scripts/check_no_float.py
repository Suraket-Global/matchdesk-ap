"""CI-04 lint: no binary floats in money and quantity code (TRD section 8.4).

Checks ``matchdesk/matching`` and ``matchdesk/core/money.py`` by default, or the
files given as arguments. Fails on float literals, ``float(...)`` calls and
``round(...)`` (rounding belongs to ``core.money``). Exit status 1 on any hit.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = [ROOT / "src/matchdesk/matching", ROOT / "src/matchdesk/core/money.py"]


def _files(targets: list[Path]) -> list[Path]:
    out: list[Path] = []
    for t in targets:
        out.extend(sorted(t.rglob("*.py")) if t.is_dir() else [t])
    return out


def check(path: Path) -> list[str]:
    problems: list[str] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            problems.append(f"{path}:{node.lineno}: float literal")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "float":
                problems.append(f"{path}:{node.lineno}: float() call")
            if node.func.id == "round":
                problems.append(f"{path}:{node.lineno}: round() outside core.money helpers")
    return problems


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv] or DEFAULT_TARGETS
    problems = [p for f in _files(targets) for p in check(f)]
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
