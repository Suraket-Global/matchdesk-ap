"""Column type shorthands following schema.md section 2."""

from __future__ import annotations

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import UUID

MONEY = Numeric(14, 2, asdecimal=True)
PRICE = Numeric(14, 6, asdecimal=True)
QTY = Numeric(14, 4, asdecimal=True)
UUIDT = UUID(as_uuid=True)


def enum_check(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} in ({joined})"
