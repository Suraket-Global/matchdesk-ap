"""UT-08 (arithmetic gates) and UT-17 (only the controller confirms "not received")."""

from __future__ import annotations

import pytest

from matchdesk.core import ForbiddenError
from matchdesk.exceptions import check_resolution_allowed
from matchdesk.extraction import verification_gates


def test_ut08_lines_plus_tax_must_equal_total():
    doc = {
        "lines": [{"qty": "1", "unit_price": "1223.33", "amount": "1223.33"}],
        "tax_total": "61.17",
        "total": "1248.50",
    }
    gates = verification_gates(doc)
    assert gates["lines_plus_tax_equals_total"] is False  # 1,284.50 != 1,248.50
    assert not all(gates.values())
    doc["total"] = "1284.50"
    assert all(verification_gates(doc).values())


def test_ut17_only_controller_confirms_not_received():
    check_resolution_allowed("controller", "receipt_absent", "confirmed_not_received")
    with pytest.raises(ForbiddenError):
        check_resolution_allowed("clerk", "receipt_absent", "confirmed_not_received")
    with pytest.raises(ForbiddenError):
        check_resolution_allowed("controller", "receipt_absent", "confirmed_overbilling")
    with pytest.raises(ForbiddenError):
        check_resolution_allowed("clerk", "receipt_absent", "waived", bulk=True)
    with pytest.raises(ForbiddenError):
        check_resolution_allowed("viewer", "price_variance", "waived")
