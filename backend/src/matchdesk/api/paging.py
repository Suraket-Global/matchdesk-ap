"""Keyset paging in the order a screen shows (B10, outside QA item 10; the B8 queue pattern).

A list that the browser displays by document date (invoices), by period (reports) or newest first
(receiving imports) is sorted by the server in that order, with the id as the tie-break, and pages
with an opaque cursor holding the last row's sort key. Paging by id while the browser sorted the
loaded rows let an old invoice appear in the middle of a later page.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import tuple_

Parse = Callable[[str], Any]
AS_DATE: Parse = date.fromisoformat
AS_DATETIME: Parse = datetime.fromisoformat
AS_UUID: Parse = uuid.UUID


def AS_INT(v: str) -> int:
    return int(v)


def AS_TEXT(v: str) -> str:
    return v


def encode(values: Sequence[Any]) -> str:
    raw = json.dumps([v.isoformat() if hasattr(v, "isoformat") else str(v) for v in values]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str, parsers: Sequence[Parse]) -> list[Any]:
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if len(raw) != len(parsers):
            raise ValueError("length")
        return [p(str(v)) for p, v in zip(parsers, raw, strict=True)]
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(422, "cursor is not valid for this list; reload the first page") from None


def keyset(
    q: Any,
    keys: Sequence[Any],
    parsers: Sequence[Parse],
    cursor: str | None,
    n: int,
    descending: bool = False,
) -> Any:
    """Order ``q`` by ``keys`` (the last one unique, normally the id), all in one direction, add the
    key values as trailing columns, start after ``cursor`` and fetch ``n + 1`` rows."""
    q = q.add_columns(*keys).order_by(*[k.desc() if descending else k.asc() for k in keys]).limit(n + 1)
    if cursor:
        after = decode(cursor, parsers)
        row = tuple_(*keys)
        q = q.where(row < tuple_(*after) if descending else row > tuple_(*after))
    return q


def page(rows: Sequence[Any], key_count: int, n: int) -> tuple[list[Any], str | None]:
    """Split fetched rows into the page (key columns removed) and the next cursor."""
    shown = [tuple(r)[:-key_count] for r in rows[:n]]
    nxt = encode(tuple(rows[n - 1])[-key_count:]) if len(rows) > n else None
    return shown, nxt
