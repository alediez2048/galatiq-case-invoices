from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from invoice_processing.money import (
    ONE_CENT,
    DecimalStr,
    UnsupportedCurrencyError,
    compare,
    format_money,
    parse_decimal,
    quantize,
)


def test_parse_decimal_is_exact():
    assert parse_decimal("0.1") + parse_decimal("0.2") == Decimal("0.3")
    assert parse_decimal(5) == Decimal("5")


@pytest.mark.parametrize("bad", [0.1, True])
def test_parse_decimal_rejects_float_and_bool(bad):
    with pytest.raises(TypeError):
        parse_decimal(bad)


@pytest.mark.parametrize("bad", ["$5,000.00", "abc", "", "1,000", "NaN", "Infinity"])
def test_parse_decimal_rejects_messy_or_non_finite_text(bad):
    with pytest.raises(ValueError):
        parse_decimal(bad)


def test_quantize_half_up():
    assert quantize(Decimal("2.345"), "USD") == Decimal("2.35")
    assert quantize(Decimal("2.344"), "USD") == Decimal("2.34")
    assert quantize(Decimal("1"), "EUR") == Decimal("1.00")


def test_quantize_unknown_currency():
    with pytest.raises(UnsupportedCurrencyError):
        quantize(Decimal("1"), "GBP")


@pytest.mark.parametrize(
    ("stated", "computed", "within"),
    [("100.01", "100.00", True), ("100.02", "100.00", False), ("22562.80", "22512.80", False)],
)
def test_compare_tolerance(stated, computed, within):
    diff = compare(Decimal(stated), Decimal(computed), "USD")
    assert diff.within_tolerance is within
    assert diff.difference == Decimal(stated) - Decimal(computed)


def test_one_cent_constant():
    assert ONE_CENT == Decimal("0.01")


def test_format_money():
    assert format_money(Decimal("5000"), "USD") == "USD 5,000.00"
    assert format_money(Decimal("4125.5"), "EUR") == "EUR 4,125.50"


class _M(BaseModel):
    amount: DecimalStr


def test_decimal_str_round_trip_and_float_rejection():
    m = _M(amount=Decimal("22512.80"))
    assert m.model_dump_json() == '{"amount":"22512.80"}'
    assert _M.model_validate_json(m.model_dump_json()).amount == Decimal("22512.80")
    with pytest.raises(ValidationError):
        _M(amount=22512.8)


def test_compare_uses_unrounded_difference():
    # A sub-cent difference is still a difference, and 0.014 exceeds the one-cent tolerance.
    assert compare(Decimal("100.004"), Decimal("100.00"), "USD").difference == Decimal("0.004")
    assert compare(Decimal("100.014"), Decimal("100.00"), "USD").within_tolerance is False


@pytest.mark.parametrize("raw", ["5E+3", "5000", "5000.0", "5000.00", "5000.004"])
def test_canonical_amount_renders_one_form(raw):
    from invoice_processing.money import canonical_amount

    assert canonical_amount(Decimal(raw), "USD") == "5000.00"
