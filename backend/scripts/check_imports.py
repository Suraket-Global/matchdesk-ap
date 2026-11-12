"""Top-level import rule (TRD section 5; B1-009).

A module imports another module only through names exported from its top level
(``from matchdesk.qbo import X``). The one exception is an ORM read model
(``matchdesk.<module>.models``), allowed only for the importer and target pairs
in ``MODEL_IMPORTS``. ``schema_registry`` (which loads every model for
migrations) is exempt. Exit status 1 on any violation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "matchdesk"

MODEL_IMPORTS: dict[str, set[str]] = {
    "exceptions": {"qbo", "receiving", "intake"},  # assemble match inputs (TRD 5, B1)
    "intake": {
        "extraction",
        "tenancy",
        "qbo",
        "identity",
    },  # extraction runs; idempotency keys; vendor and PO lookup (B3); intake address of a tenant (B7)
    "receiving": {"qbo", "intake"},  # PO lines to map rows to; the shared documents table (B3)
    # frozen report snapshot (B3); weekly summary recipients and tenant name (B7)
    "reporting": {"exceptions", "intake", "qbo", "receiving", "identity"},
    # read endpoints (B3); operator console and support grants (B7)
    "api": {"exceptions", "intake", "tenancy", "qbo", "receiving", "reporting", "identity"},
}
EXEMPT = {"schema_registry"}


def module_of(path: Path, pkg: Path) -> str:
    rel = path.relative_to(pkg)
    return rel.parts[0].removesuffix(".py")


def targets(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            out.extend((node.lineno, a.name) for a in node.names)
    return out


def check(pkg: Path = PKG) -> list[str]:
    problems: list[str] = []
    for path in sorted(pkg.rglob("*.py")):
        importer = module_of(path, pkg) if path.parent != pkg or path.name != "__init__.py" else ""
        if importer in EXEMPT or not importer:
            continue
        for lineno, name in targets(ast.parse(path.read_text(), filename=str(path))):
            parts = name.split(".")
            if parts[0] != "matchdesk" or len(parts) < 3:
                continue
            target, sub = parts[1], parts[2]
            if target == importer:
                continue
            if sub == "models" and target in MODEL_IMPORTS.get(importer, set()):
                continue
            problems.append(f"{path.relative_to(pkg.parent)}:{lineno}: {importer} imports {name}")
    return problems


def main(argv: list[str]) -> int:
    pkg = Path(argv[0]) if argv else PKG
    problems = check(pkg)
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
