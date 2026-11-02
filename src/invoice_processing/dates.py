"""Invoice date parsing. Nothing here reads the system clock."""

import re
from datetime import date

_MONTHS = {
    name: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_RELATIVE = {"yesterday", "today", "tomorrow", "asap", "immediately", "immediate", "now"}
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_MON_D_Y = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})")
_D_MON_Y = re.compile(r"(\d{1,2})-([A-Za-z]+)-(\d{4})")
_SLASH = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


class RelativeDate(ValueError):
    """A word such as "yesterday" or "ASAP": no calendar date can be derived from it."""


class AmbiguousDate(ValueError):
    """NN/NN/YYYY where both parts are at most 12 and differ."""


def _month(name: str, raw: str) -> int:
    try:
        return _MONTHS[name.casefold()]
    except KeyError:
        raise ValueError(f"unknown month in {raw!r}") from None


def parse_date(raw: str) -> date:
    text = raw.strip()
    if text.casefold() in _RELATIVE:
        raise RelativeDate(raw)
    if m := _ISO.fullmatch(text):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if m := _MON_D_Y.fullmatch(text):
        return date(int(m[3]), _month(m[1], raw), int(m[2]))
    if m := _D_MON_Y.fullmatch(text):
        return date(int(m[3]), _month(m[2], raw), int(m[1]))
    if m := _SLASH.fullmatch(text):
        a, b, year = int(m[1]), int(m[2]), int(m[3])
        if a == b or b > 12:  # MM/DD/YYYY (equal parts read the same either way)
            return date(year, a, b)
        if a > 12:  # DD/MM/YYYY
            return date(year, b, a)
        raise AmbiguousDate(raw)
    raise ValueError(f"not a date: {raw!r}")
