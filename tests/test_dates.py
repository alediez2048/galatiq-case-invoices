from datetime import date

import pytest

from invoice_processing.dates import AmbiguousDate, RelativeDate, parse_date


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-01-15", date(2026, 1, 15)),
        ("Jan 30 2026", date(2026, 1, 30)),
        ("January 27, 2026", date(2026, 1, 27)),
        ("26-Jan-2026", date(2026, 1, 26)),
        ("01/28/2026", date(2026, 1, 28)),
        ("28/01/2026", date(2026, 1, 28)),
        ("03/03/2026", date(2026, 3, 3)),
        (" 26-jan-2026 ", date(2026, 1, 26)),
    ],
)
def test_formats(raw, expected):
    assert parse_date(raw) == expected


def test_ambiguous():
    with pytest.raises(AmbiguousDate):
        parse_date("02/03/2026")


@pytest.mark.parametrize("raw", ["yesterday", "ASAP", "Immediately", " now "])
def test_relative(raw):
    with pytest.raises(RelativeDate):
        parse_date(raw)


@pytest.mark.parametrize(
    "raw", ["", "soon", "2026-13-01", "13/13/2026", "Foo 3 2026", "Feb 30 2026"]
)
def test_invalid(raw):
    with pytest.raises(ValueError) as exc:
        parse_date(raw)
    assert not isinstance(exc.value, (AmbiguousDate, RelativeDate))
