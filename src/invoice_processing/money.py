"""Exact decimal money handling. Money is never a float."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer

MINOR_UNITS: dict[str, int] = {"USD": 2, "EUR": 2}
ONE_CENT = Decimal("0.01")


class UnsupportedCurrencyError(ValueError):
    pass


def parse_decimal(value: str | int | Decimal) -> Decimal:
    """Convert a clean numeric value to Decimal. Messy source text is not parsed here."""
    # bool is an int subclass, so it must be rejected before the int branch.
    if isinstance(value, bool | float):
        raise TypeError(f"{type(value).__name__} is not an exact money value")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty value is not a number")
        try:
            result = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"not a plain decimal number: {value!r}") from None
    else:
        raise TypeError(f"unsupported type: {type(value).__name__}")
    if not result.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return result


def quantize(amount: Decimal, currency: str) -> Decimal:
    if currency not in MINOR_UNITS:
        raise UnsupportedCurrencyError(f"unsupported currency: {currency!r}")
    return amount.quantize(Decimal(1).scaleb(-MINOR_UNITS[currency]), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class MoneyDifference:
    difference: Decimal
    within_tolerance: bool


def compare(stated: Decimal, computed: Decimal, currency: str) -> MoneyDifference:
    difference = quantize(stated - computed, currency)
    return MoneyDifference(difference=difference, within_tolerance=abs(difference) <= ONE_CENT)


def format_money(amount: Decimal, currency: str) -> str:
    return f"{currency} {quantize(amount, currency):,}"


def _reject_float(value: Any) -> Any:
    # Pydantic only converts ValueError into a ValidationError, so raise that here.
    if isinstance(value, float):
        raise ValueError("float is not an exact money value; pass a string or Decimal")
    return value


DecimalStr = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    PlainSerializer(str, return_type=str, when_used="json"),
]
