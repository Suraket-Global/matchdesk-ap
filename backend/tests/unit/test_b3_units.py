"""B3 unit tests: QuickBooks real-client placeholders refuse, local PDF reading, CSV/XLSX parsing."""

from __future__ import annotations

import dataclasses

import pytest

from matchdesk.core import load_settings
from matchdesk.qbo import (
    IntuitQboReader,
    IntuitTokenEndpoint,
    PageQuery,
    QboNotConfiguredError,
    RecordedQboReader,
    reader_from_settings,
)


def test_intuit_mode_is_selected_by_settings_and_refuses_without_an_account() -> None:
    settings = dataclasses.replace(load_settings(), qbo_mode="intuit")
    reader = reader_from_settings(settings)
    assert isinstance(reader, IntuitQboReader)
    with pytest.raises(QboNotConfiguredError):
        reader.page("PurchaseOrder", 1, 10, PageQuery())
    with pytest.raises(QboNotConfiguredError):
        IntuitTokenEndpoint(settings)


def test_readers_have_no_write_method() -> None:
    for cls in (IntuitQboReader, RecordedQboReader):
        names = {n for n in dir(cls) if not n.startswith("_")}
        assert not {n for n in names if any(w in n for w in ("write", "create", "update", "delete", "post"))}
