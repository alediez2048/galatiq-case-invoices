"""Evidence-checked extraction assist (P3-05): when to ask the model, and what to believe.

The model sees bounded excerpts of this invoice's source and may propose values for fields
the parser left empty. A proposal is applied only when its quote is found verbatim at the
excerpt location it names and that quote contains the proposed value; a field the parser
already read is never replaced (Decision 7). Nothing here calls a model.
"""

import re
from collections.abc import Collection, Mapping, Sequence
from typing import Literal

from invoice_processing.codes import DEFAULT_SEVERITY, FindingCode, Severity, SourceFormat
from invoice_processing.dates import parse_date
from invoice_processing.normalize import EMBEDDED_INSTRUCTIONS, parse_amount, vendor_key
from invoice_processing.schemas import (
    EvidenceRef,
    ExtractionAssistRequest,
    FieldProposal,
    InvoiceDraft,
    NormalizationEvent,
    SourceExcerpt,
    ValidationFinding,
)

Verdict = Literal["accept", "unsupported", "disagree", "ignore"]

DRAFT_FIELDS: dict[str, str] = {
    "vendor": "vendor_raw",
    "invoice_number": "invoice_number_raw",
    "invoice_date": "invoice_date_raw",
    "due_date": "due_date_raw",
    "currency": "currency_raw",
    "subtotal": "subtotal_raw",
    "tax": "tax_raw",
    "shipping": "shipping_raw",
    "total": "total_raw",
}
_AMOUNT_FIELDS = {"subtotal", "tax", "shipping", "total"}
_DATE_FIELDS = {"invoice_date", "due_date"}
# Literals inside a quote that a proposed amount or date must match exactly once parsed.
_AMOUNT_LITERAL = re.compile(r"-?[$€£]?-?\d[\d,]*(?:\.\d+)?")
_DATE_LITERAL = re.compile(
    r"\d{4}-\d{2}-\d{2}|[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}-[A-Za-z]+-\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
)
# Required fields whose absence triggers assist (Decision 6), with the code validation uses.
_REQUIRED = (
    ("vendor", FindingCode.missing_vendor),
    ("invoice_number", FindingCode.missing_invoice_number),
    ("due_date", FindingCode.missing_due_date),
    ("total", FindingCode.missing_total),
)
_TRIGGER = frozenset({Severity.review, Severity.blocker})
_PAGE_BREAK = "\n\f\n"  # joins PDF pages in the extracted text (see parsers/pdf.py)
_LINE_CHARS = 300  # one excerpt line at most; longer source lines are cut
_OBSERVED_CHARS = 200  # model text kept on a finding
_TOKEN = re.compile(r"\w+")


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def missing_fields(draft: InvoiceDraft) -> list[tuple[FindingCode, str]]:
    missing = [(code, f) for f, code in _REQUIRED if _blank(getattr(draft, DRAFT_FIELDS[f]))]
    if not draft.lines:
        missing.append((FindingCode.missing_line_items, "lines"))
    return missing


def needs_assist(draft: InvoiceDraft, findings: Sequence[ValidationFinding]) -> bool:
    """Decision 6: a review-or-worse extraction/normalization finding, or a missing field.

    `findings` are the ingestion findings (normalization plus extraction issues); info-only
    findings such as `unparsed_line` never trigger a model call.
    """
    return bool(missing_fields(draft)) or any(f.severity in _TRIGGER for f in findings)


def issue_labels(draft: InvoiceDraft, findings: Sequence[ValidationFinding]) -> list[str]:
    """`code:field` labels for the request, e.g. "missing_vendor:vendor"."""
    labels = [f"{code.value}:{field}" for code, field in missing_fields(draft)]
    labels += [
        f"{f.code.value}:{f.field}" if f.field else f.code.value
        for f in findings
        if f.severity in _TRIGGER
    ]
    return list(dict.fromkeys(labels))


def _located_lines(text: str, fmt: SourceFormat):
    if fmt is SourceFormat.pdf:
        for p, page in enumerate(text.split(_PAGE_BREAK), start=1):
            for n, line in enumerate(page.splitlines(), start=1):
                yield f"page:{p},line:{n}", line
        return
    prefix = "row" if fmt is SourceFormat.csv else "line"
    for n, line in enumerate(text.splitlines(), start=1):
        yield f"{prefix}:{n}", line


def excerpts(text: str, fmt: SourceFormat, limit: int) -> list[SourceExcerpt]:
    """Non-blank source lines in document order, at most `limit` characters in total.

    Locations follow the parsers' line conventions (`line:N`, `page:P,line:N`, `row:N`);
    structured formats (JSON, XML) are excerpted by physical line as well.
    """
    out: list[SourceExcerpt] = []
    used = 0
    for location, line in _located_lines(text, fmt):
        line = line.strip()[:_LINE_CHARS]
        if not line:
            continue
        if used + len(line) > limit:
            break
        out.append(SourceExcerpt(location=location, text=line))
        used += len(line)
    return out


def build_request(
    draft: InvoiceDraft,
    findings: Sequence[ValidationFinding],
    source_text: str,
    fmt: SourceFormat,
    known_items: Collection[str],
    excerpt_chars: int,
) -> ExtractionAssistRequest:
    return ExtractionAssistRequest(
        issues=issue_labels(draft, findings),
        excerpts=excerpts(source_text, fmt, excerpt_chars),
        known_items=sorted(known_items),
    )


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.replace("$", "").replace(",", "").casefold())


def _same(field: str, a: str, b: str) -> bool:
    if field in _AMOUNT_FIELDS:
        try:
            return parse_amount(a) == parse_amount(b)
        except ValueError:
            pass
    return vendor_key(a) == vendor_key(b)


def _parsed_literals(quote: str, pattern: re.Pattern[str], parser) -> list:
    out = []
    for m in pattern.finditer(quote):
        try:
            out.append(parser(m[0]))
        except ValueError:  # includes ambiguous and relative dates: never a match
            continue
    return out


def _collapse(text: str) -> str:
    return " ".join(text.casefold().split())


def _value_stated(field: str, value: str, quote: str) -> bool:
    """The quote states exactly this value: amounts and dates by parsed equality (sign and
    day/month order preserved), other fields as a contiguous substring."""
    try:
        if field in _AMOUNT_FIELDS:
            return parse_amount(value) in _parsed_literals(quote, _AMOUNT_LITERAL, parse_amount)
        if field in _DATE_FIELDS:
            return parse_date(value) in _parsed_literals(quote, _DATE_LITERAL, parse_date)
    except ValueError:
        return False
    return _collapse(value) in _collapse(quote)


def _supported(p: FieldProposal, source_lines: Mapping[str, str]) -> bool:
    source = source_lines.get(p.location)
    if source is None or not p.quote.strip() or p.quote not in source:
        return False
    if EMBEDDED_INSTRUCTIONS.search(source):  # never take a value from text aimed at a model
        return False
    value, quoted = _tokens(p.value), set(_tokens(p.quote))
    if not value or not all(t in quoted for t in value):  # floor: every token is quoted
        return False
    return _value_stated(p.field, p.value.strip(), p.quote)


def check_proposal(
    p: FieldProposal, source_lines: Mapping[str, str], draft: InvoiceDraft
) -> Verdict:
    """accept | unsupported (evidence fails) | disagree / ignore (field already has a value)."""
    if not _supported(p, source_lines):
        return "unsupported"
    current = getattr(draft, DRAFT_FIELDS[p.field])
    if _blank(current):
        return "accept"
    return "ignore" if _same(p.field, current, p.value) else "disagree"


def _finding(code: FindingCode, p: FieldProposal, **extra) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=DEFAULT_SEVERITY[code],
        field=p.field,
        observed=p.value[:_OBSERVED_CHARS],
        **extra,
    )


def apply(
    draft: InvoiceDraft,
    proposals: Sequence[FieldProposal],
    source_lines: Mapping[str, str],
    provenance: str,
) -> tuple[InvoiceDraft, list[ValidationFinding], list[str]]:
    """A copy of `draft` with accepted proposals filled in, findings for the rest, and the
    accepted field names in order.

    Proposals are checked in order against the amended draft, so a second proposal for a
    field filled by the first is treated like any other already-present value.
    """
    amended = draft.model_copy(deep=True)
    findings: list[ValidationFinding] = []
    accepted: list[str] = []
    for p in proposals:
        verdict = check_proposal(p, source_lines, amended)
        ref = EvidenceRef(source_id=draft.source_id, location=p.location, snippet=p.quote)
        if verdict == "accept":
            value = p.value.strip()
            setattr(amended, DRAFT_FIELDS[p.field], value)
            accepted.append(p.field)
            amended.field_evidence[p.field] = [ref]
            amended.normalization_events.append(
                NormalizationEvent(
                    field=p.field,
                    raw_value=None,
                    normalized_value=value,
                    evidence=[ref],
                    provenance=provenance,
                )
            )
        elif verdict == "unsupported":
            # The location and quote are unverified model text: kept out of the evidence.
            findings.append(_finding(FindingCode.model_proposal_unsupported, p))
        elif verdict == "disagree":
            current = getattr(amended, DRAFT_FIELDS[p.field])
            findings.append(
                _finding(FindingCode.model_parser_disagreement, p, expected=current, evidence=[ref])
            )
    return amended, findings, accepted
