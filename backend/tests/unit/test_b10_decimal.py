"""B10 (2026-11-13), outside QA items 3 and 4: one set of expected values for the backend and the web
app (``fixtures/decimal_cases.json``), half-up rounding of negatives, and typed or file numbers
read without guessing. All numbers synthetic."""

from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from matchdesk.core import line_amount, parse_typed_decimal, round_cents, round_half_up
from matchdesk.extraction import local_pdf
from matchdesk.reporting import backtest, weekly

CASES = json.loads((Path(__file__).parents[2] / "fixtures" / "decimal_cases.json").read_text())


@pytest.mark.parametrize("c", CASES["line_amount"], ids=lambda c: f"{c['qty']}x{c['unit_price']}")
def test_line_amount_matches_the_shared_fixture(c: dict[str, str]) -> None:
    assert line_amount(D(c["qty"]), D(c["unit_price"])) == D(c["amount"]), c["why"]


@pytest.mark.parametrize("c", CASES["round_cents"], ids=lambda c: c["value"])
def test_round_cents_matches_the_shared_fixture(c: dict[str, str]) -> None:
    assert round_cents(D(c["value"])) == D(c["cents"])


@pytest.mark.parametrize("c", CASES["money_input"], ids=lambda c: repr(c["input"]))
def test_typed_money_matches_the_shared_fixture(c: dict[str, object]) -> None:
    if c.get("error"):
        with pytest.raises(ValueError):
            parse_typed_decimal(str(c["input"]), places=2, whole=12)
    else:
        assert parse_typed_decimal(str(c["input"]), places=2, whole=12) == c["value"]


def test_percentages_round_half_up_not_half_even() -> None:
    # 1 of 32 is 3.125 %: half even gave 3.12; the documented rule gives 3.13. Weekly: 1 of 16 = 6.25.
    assert backtest._pct(1, 32) == D("3.13")
    assert round_half_up(D("6.25"), D("0.1")) == D("6.3")
    assert round_half_up(D("-6.25"), D("0.1")) == D("-6.3")
    assert "round_half_up" in Path(weekly.__file__).read_text()


def test_local_reader_does_not_guess_a_comma_decimal() -> None:
    assert local_pdf._money("1,000.50") == D("1000.50")
    assert local_pdf._money("1,5") is None  # was read as 15
    assert local_pdf._money("1.000,5") is None  # was read as 1.0005
