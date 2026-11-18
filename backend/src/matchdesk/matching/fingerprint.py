"""Input fingerprint for match runs (T-4.1.6 (b); TRD 6.3 "Match runs are unique on input fingerprint").

The fingerprint depends only on the set of inputs, never on their order: every
collection is serialised, then sorted, before hashing.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import date
from decimal import Decimal
from enum import Enum

from matchdesk.matching.types import MatchInput

# Raise this whenever the rules' code changes what a stored result would be. It is part of every
# fingerprint, so after a deploy every stored result reads as out of date and the worker's minute
# tick matches it again (live test 2026-11-18: an engine fix left the old results in place).
ENGINE_VERSION = "2026-11-18.1"


def _canonical(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _canonical(getattr(value, f.name))
            for f in dataclasses.fields(value)
            if not (
                f.metadata.get("fingerprint") == "omit_if_default" and getattr(value, f.name) == f.default
            )
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        # normalise so 4.2 and 4.20 hash alike
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (tuple, list, frozenset, set)):
        items = [_canonical(v) for v in value]
        return sorted(items, key=lambda x: json.dumps(x, sort_keys=True))
    if isinstance(value, float):
        raise TypeError("floats are not allowed in match inputs")
    return value


def assert_no_floats(value: object) -> None:
    """Refuse a binary float anywhere in the input (TRD 8.4); raises ``TypeError``."""
    if isinstance(value, float):
        raise TypeError("floats are not allowed in match inputs")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            assert_no_floats(getattr(value, f.name))
    elif isinstance(value, (tuple, list, frozenset, set)):
        for v in value:
            assert_no_floats(v)


def input_fingerprint(inp: MatchInput) -> bytes:
    text = json.dumps(
        {"engine": ENGINE_VERSION, "input": _canonical(inp)}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(text.encode()).digest()
