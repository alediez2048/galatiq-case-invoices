"""Evidence for review corrections (Decision 8): locate a cited source location, tell
whether another field owns it, and check that the located text supports a value."""

import csv
import io
import json
import re
from datetime import date
from decimal import Decimal
from typing import Any
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from invoice_processing.codes import SourceFormat
from invoice_processing.dates import parse_date
from invoice_processing.normalize import fix_ocr_digits, parse_amount
from invoice_processing.schemas import NormalizedInvoice

_PAGE_BREAK = "\n\f\n"  # joins PDF pages in the extracted text (see parsers/pdf.py)


def _text_line(text: str, page: int | None, line: int) -> str | None:
    pages = text.split(_PAGE_BREAK) if page is not None else [text]
    index = (page or 1) - 1
    if index < 0 or index >= len(pages):
        return None
    lines = pages[index].splitlines()
    return lines[line - 1] if 1 <= line <= len(lines) else None


def _csv_row(text: str, number: int) -> str | None:
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        for row in reader:
            if reader.line_num == number:
                out = io.StringIO()
                csv.writer(out).writerow(row)
                return out.getvalue().rstrip("\r\n")
    except csv.Error:
        return None
    return None


_JSON_STEP = re.compile(r"\.([^.\[\]]+)|\[(\d+)\]")


def _json_value(text: str, path: str) -> str | None:
    try:
        node: Any = json.loads(text)
    except ValueError:
        return None
    rest = path[1:]
    steps = list(_JSON_STEP.finditer(rest))
    if "".join(m.group(0) for m in steps) != rest:
        return None
    for m in steps:
        key, idx = m.groups()
        if key is not None:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        else:
            if not isinstance(node, list) or int(idx) >= len(node):
                return None
            node = node[int(idx)]
    return json.dumps(node, ensure_ascii=False, default=str)


_XML_STEP = re.compile(r"^([A-Za-z_][\w.\-]*)(?:\[(\d+)\])?$")


def _xml_text(text: str, path: str) -> str | None:
    try:
        node: Element = fromstring(
            text.encode(), forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except (ParseError, ValueError, DefusedXmlException):
        return None
    steps = path.strip("/").split("/")
    if steps[0] != node.tag:
        return None
    for step in steps[1:]:
        m = _XML_STEP.match(step)
        if m is None:
            return None
        children = [c for c in node if c.tag == m[1]]
        pos = int(m[2]) if m[2] else 1
        if not 1 <= pos <= len(children):
            return None
        node = children[pos - 1]
    if len(node) == 0:
        return "".join(node.itertext()).strip()
    return " ".join(f"{c.tag}={''.join(c.itertext()).strip()}" for c in node)


_LINE_LOC = re.compile(r"(?:page:(\d+),)?line:(\d+)")
_ROW_LOC = re.compile(r"row:(\d+)(?:,col:.+)?")


def _canonical_line(text: str, page: int | None, line: int) -> str | None:
    """`line:N` for non-paged text, `page:P,line:N` for paged (PDF) text; a whole-text line
    number is mapped to its page. None when the line does not exist (a page break is not a
    source line)."""
    pages = text.split(_PAGE_BREAK)
    counts = [len(p.splitlines()) for p in pages]
    if page is None:
        start = 0  # whole-text lines before the current page
        for index in range(len(pages)):
            if start < line <= start + counts[index]:
                page, line = index + 1, line - start
                break
            start = len((_PAGE_BREAK.join(pages[: index + 1]) + _PAGE_BREAK).splitlines())
        else:
            return None
    if not (1 <= page <= len(pages) and 1 <= line <= counts[page - 1]):
        return None
    return f"line:{line}" if len(pages) == 1 else f"page:{page},line:{line}"


def _canonical_json(path: str) -> str | None:
    rest = path[1:]
    steps = list(_JSON_STEP.finditer(rest))
    if "".join(m.group(0) for m in steps) != rest:
        return None
    return "$" + "".join(
        f".{key}" if key is not None else f"[{int(i)}]" for key, i in (m.groups() for m in steps)
    )


def _canonical_xml(path: str) -> str | None:
    steps = path.strip("/").split("/")
    if not steps[0] or _XML_STEP.fullmatch(steps[0]) is None or "[" in steps[0]:
        return None
    out = [steps[0]]
    for step in steps[1:]:
        m = _XML_STEP.match(step)
        if m is None:
            return None
        out.append(f"{m[1]}[{int(m[2]) if m[2] else 1}]")
    return "/" + "/".join(out)


def canonical_location(location: str, text: str) -> str | None:
    """The one spelling of a location, so that two spellings `locate` reads the same way
    compare equal (Decision 8): line numbers without leading zeros, `page:1` dropped for
    non-paged text and added for paged text, CSV rows without the column, JSON indices as
    integers, XML paths with single slashes and explicit `[1]` indices. None when the
    location has no meaning (or, for lines, does not exist in `text`)."""
    if m := _LINE_LOC.fullmatch(location):
        return _canonical_line(text, int(m[1]) if m[1] else None, int(m[2]))
    if m := _ROW_LOC.fullmatch(location):
        return f"row:{int(m[1])}"
    if location.startswith("$"):
        return _canonical_json(location)
    if location.startswith("/"):
        return _canonical_xml(location)
    return None


def scheme_matches(location: str, fmt: SourceFormat) -> bool:
    """Whether `location` uses the scheme the parser records for this format: TXT
    `line:N`, PDF `page:P,line:N`, CSV `row:N[,col:…]`, JSON `$…`, XML `/…`. `locate` itself
    accepts every scheme on every format (model tools see JSON/XML as numbered lines), so a
    review citation must also pass this check, or one value has two addresses."""
    if fmt is SourceFormat.txt or fmt is SourceFormat.pdf:
        m = _LINE_LOC.fullmatch(location)
        return m is not None and (m[1] is not None) == (fmt is SourceFormat.pdf)
    if fmt is SourceFormat.csv:
        return _ROW_LOC.fullmatch(location) is not None
    if fmt is SourceFormat.json:
        return location.startswith("$")
    return fmt is SourceFormat.xml and location.startswith("/")


def locate(text: str, location: str) -> str | None:
    canonical = canonical_location(location, text)
    if canonical is None:
        return None
    if m := _LINE_LOC.fullmatch(canonical):
        return _text_line(text, int(m[1]) if m[1] else None, int(m[2]))
    if m := _ROW_LOC.fullmatch(canonical):
        return _csv_row(text, int(m[1]))
    if canonical.startswith("$"):
        return _json_value(text, canonical)
    return _xml_text(text, canonical)


# --- Which field owns a location (Decision 8) ----------------------------------------------

_LINE_FIELD = re.compile(r"^(lines\[\d+\])\.")


# The text parser records the "Tax (8%): $40.00" line under both keys: one owner.
_SAME_OWNER = {"tax_rate": "tax", "tax_rate_fraction": "tax"}


def _owner(field: str) -> str:
    """`lines[i]` for a line field; otherwise the field_evidence key (no `stated.`)."""
    m = _LINE_FIELD.match(field)
    name = m[1] if m else field.removeprefix("stated.")
    return _SAME_OWNER.get(name, name)


def _contains(outer: str, inner: str) -> bool:
    """`inner` is `outer` or, for a JSON/XML path, a path below it."""
    if inner == outer:
        return True
    if not outer.startswith(("$", "/")):
        return False
    return inner.startswith(outer) and inner[len(outer)] in ".[/"


def _same_place(a: str, b: str) -> bool:
    return _contains(a, b) or _contains(b, a)


def claimed_by_other(field: str, location: str, invoice: NormalizedInvoice, text: str) -> bool:
    """Whether `location` is a recorded evidence location of a field other than `field`:
    another header field's `field_evidence` or another line's evidence. Both sides are
    compared in their canonical spelling (against `text`, the source text); JSON and XML
    paths also match a path above or below them. A location with no canonical spelling is
    treated as claimed."""
    cited = canonical_location(location, text)
    if cited is None:
        return True
    mine = _owner(field)
    owned: list[tuple[str, str]] = [
        (_owner(name), ref.location)
        for name, refs in invoice.field_evidence.items()
        for ref in refs
    ]
    owned += [
        (f"lines[{i}]", ref.location)
        for i, line in enumerate(invoice.lines)
        for ref in line.evidence
    ]
    return any(
        owner != mine and _same_place(canonical_location(loc, text) or loc, cited)
        for owner, loc in owned
    )


# --- Does the located text support the value -----------------------------------------------

_MONEY_TOKEN = re.compile(r"\d(?:[\d.,]|(?<=\d) (?=\d))*")
_INT_TOKEN = re.compile(r"\d+")
_INTEGER = re.compile(r"\d+")
_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}
_CENT = Decimal("0.01")
_TEXT_FIELDS = frozenset({"vendor", "invoice_number"})
_DATE_FIELDS = frozenset({"invoice_date", "due_date"})


def _token_digits(token: str) -> str:
    """The token's digits in cents: whole units unless the last separator has two digits."""
    digits = re.sub(r"\D", "", token)
    sep = max(token.rfind("."), token.rfind(","))
    tail = token[sep + 1 :] if sep >= 0 else ""
    if sep < 0 or not (len(tail) == 2 and tail.isdigit()):
        digits += "00"
    return digits.lstrip("0")


def _supports_money(value: str, text: str, structured: bool) -> bool:
    try:
        amount = parse_amount(value).quantize(_CENT)
    except (ValueError, ArithmeticError):
        return False
    if structured:  # a JSON/XML scalar such as 5050.0 or "5050.00": compare as a number
        try:
            return Decimal(text.strip().strip('"')).quantize(_CENT) == amount
        except (ArithmeticError, ValueError):
            return False
    wanted = f"{abs(amount):f}".replace(".", "").lstrip("0")
    negative = amount < 0
    return any(
        _token_digits(m[0]) == wanted
        and _negative_before(text, m.start()) == negative
        and _OPEN_PAREN.search(text[: m.start()]) is None
        for m in _MONEY_TOKEN.finditer(text)
    )


_SIGN_BEFORE = re.compile(r"-\s*[$€£]?\s*$")
# "(50.00)" is an accounting negative; its sign is ambiguous, so it is never evidence.
_OPEN_PAREN = re.compile(r"\(\s*-?\s*[$€£]?\s*$")


def _negative_before(text: str, start: int) -> bool:
    """A minus sign (optionally with a currency symbol) right before the amount."""
    return _SIGN_BEFORE.search(text[:start]) is not None


def _supports_quantity(value: str, text: str) -> bool:
    if not _INTEGER.fullmatch(value) or int(value) <= 0:
        return False
    return any(int(t) == int(value) for t in _INT_TOKEN.findall(text))


def _supports_date(value: str, text: str) -> bool:
    try:
        wanted = date.fromisoformat(value)
    except ValueError:
        return False
    tokens = text.split()
    for size in (1, 2, 3):
        for i in range(len(tokens) - size + 1):
            try:
                if parse_date(" ".join(tokens[i : i + size])) == wanted:
                    return True
            except ValueError:
                continue
    return False


def _supports_currency(value: str, text: str) -> bool:
    code = value.strip().upper()
    if re.search(rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])", text, re.IGNORECASE):
        return True
    symbol = _CURRENCY_SYMBOLS.get(code)
    return symbol is not None and symbol in text


def _squash(text: str) -> str:
    return "".join(text.casefold().split())


def _is_money(field: str) -> bool:
    return field.startswith("stated.") or field.endswith((".unit_price", ".line_total"))


def is_structured(location: str) -> bool:
    """A JSON (`$…`) or XML (`/…`) path: `locate` returns one structured scalar there."""
    return location.startswith(("$", "/"))


def supports(field: str, value: str, text: str, *, structured: bool = False) -> bool:
    """Whether `text` (the located source text) shows `value` for `field`.

    For money, quantity and dates, OCR-read zeros (a letter O touching a digit) count as
    zeros; text and currency compare against the text as it is. `structured` (the location
    is a JSON/XML path) compares a money value with the located scalar as a number."""
    if _is_money(field) or field.endswith(".quantity") or field in _DATE_FIELDS:
        text = fix_ocr_digits(text) or text
    if _is_money(field):
        return _supports_money(value, text, structured)
    if field.endswith(".quantity"):
        return _supports_quantity(value, text)
    if field in _DATE_FIELDS:
        return _supports_date(value, text)
    if field == "currency":
        return _supports_currency(value, text)
    if field in _TEXT_FIELDS or field.endswith(".item"):
        wanted = _squash(value)
        return bool(wanted) and wanted in _squash(text)
    return False
