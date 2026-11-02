# Phase 2 — Full Corpus and Data Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** every one of the 20 files in `data/invoices/` produces its expected outcome in offline mode, and no identity is ever paid twice across formats or revisions.

**Architecture:** intake routes by extension and content sniffing and enforces size limits; one parser per format (TXT and PDF share one line-based text extractor) produces an `InvoiceDraft` of raw strings with per-field evidence; `normalize` applies named, evidence-backed rules (labels, items, OCR digits, dates, currency, identity keys) and emits findings; the ingestion node then checks business identity + semantic hash for duplicates and revisions before validation. The policy gate, payment guard and graph shape from Phase 1 are unchanged except for one new transition (`extracted → duplicate`) and one new payment refusal.

**Tech Stack:** Python 3.12, uv, Pydantic 2, SQLite, LangGraph 1.2, `pdfplumber` 0.11, `defusedxml` 0.7, `pypdf` 6 (dev only, for generated test PDFs), pytest, ruff.

**Spec:** `docs/PRD.md` (Phase 2 section), `docs/requirements.md` (sample acceptance matrix, business policy), `docs/contraints.md` (operational bounds, security), `docs/systemsdesign.md` (revision policy), and tickets `docs/tickets/P2-01` … `P2-11`. The "Phase 1 carry-overs" table in `docs/tickets/README.md` lists extra items folded into tasks below.

## Global Constraints

- Money is `Decimal` end to end; never `float`. JSON uses `parse_float=Decimal`; XML/CSV text goes straight to `Decimal`.
- Missing values are never fabricated; raw values are preserved; every normalization change is a `NormalizationEvent` with `provenance="rule:<name>"` and evidence.
- No fuzzy or edit-distance matching for items or vendors.
- Limits: 10 MiB per input (`10 * 1024 * 1024` bytes), 25 PDF pages, 200 invoice lines.
- Offline mode opens no socket (autouse `no_network` fixture; `INVOICE_NETWORK_GUARD=1` for subprocesses).
- Tests never touch the repo-root `inventory.db`; files in `data/invoices/` are never modified; generated fixtures live in `tmp_path` (only PDF text snapshots are committed, under `tests/fixtures/pdf_text/`).
- Logs and audit payloads never contain API keys, environment variables, full invoice text, or model reasoning. (Extracted PDF text may be stored in `sources.extracted_text`, never logged.)
- CLI exit codes unchanged: 0 business outcome (incl. `duplicate`), 1 `failed`, 2 usage/intake/database errors.
- Finding codes are stable identifiers; tests assert codes and statuses, not prose.
- `uv run ruff check .` and `uv run ruff format --check .` clean; line length 100.
- Commits end with the trailer lines given in the session (Co-Authored-By / Claude-Session).

## Decisions taken in this plan

Each is a ruling on something the tickets leave open; the cost if wrong is noted.

1. **1012 outcome is `paid_mock`** (P2-11 "decision needed"): every correction is rule-backed and verified (OCR line total equals qty × price), so nothing is unresolved. Cost: one table row and the ticket note flip to `needs_review` if the user prefers OCR to always stop.
2. **Size, extension and content sniffing fail at intake** (`IntakeError`, no run, exit 2 — the mockup says oversized input does "not start a run"). PDF preflight, parse errors and the 200-line cap fail during extraction (run `failed`, exit 1, `error_code` + `error_message`). Cost: moving a check between layers.
3. **Generated fixtures are built in `tmp_path` by `tests/fixture_factory.py`**, not committed under `tests/fixtures/` (avoids an 11 MiB file in git). Cost: none functional.
4. **A PDF that needs a password is `pdf_encrypted`; a permissions-only encrypted PDF (empty user password) opens in any viewer and is processed.** Cost: one branch.
5. **Labels match case-insensitively; case-only differences are not aliases; `Total Amount` is canonical** (keeps 1001 alias-free). Cost: a few extra/missing alias events.
6. **Item canonicalization is case-sensitive** (`Widget A` → `WidgetA`, not `widgeta` → `WidgetA`). Cost: a lower-case variant stays unknown.
7. **Slash dates:** exactly one component > 12 decides the reading (`01/28/2026` → Jan 28; `28/01/2026` → Jan 28); both ≤ 12 and different → `ambiguous_date`; equal components → accepted. Cost: DD/MM inputs with day ≤ 12 go to review.
8. **The gate keeps `R2_non_usd`** as an independent backstop, so 1014 carries both `unsupported_currency` (normalization) and `non_usd_currency` (gate). Cost: two findings for one cause.
9. **USD is assumed whenever no currency code and no non-`$` symbol is present** (needed for 1006/1015 CSVs, which have no `$`), always with a `currency_assumed_usd` finding; evidence is the first field whose raw value contains `$` (Phase 1 Ruling A), or none. Cost: none for the corpus.
10. **Semantic duplicates end the run `extracted → duplicate`** inside the ingestion node; **revisions and version conflicts are `review` findings** that continue through validation and the gate (so blockers still reject). Cost: graph routing change if a dedicated node is preferred later.
11. **`SCHEMA_VERSION` becomes 4 with no DDL change**, because identity keys and normalization change meaning; a Phase 1 ledger could otherwise pay a 1011 PDF after a 1011 TXT. Old databases are refused with the existing message. Cost: user deletes a local `inventory.db`.
12. **JSON/XML `tax_rate` is a fraction** → new draft field `tax_rate_fraction_raw`; text `Tax (N%)` stays a percent in `tax_rate_raw`. Cost: none.
13. **Extraction issue codes are `FindingCode`s** and every issue becomes a finding in the ingestion node. An incomplete CSV field/value group becomes a `DraftLine` with missing fields (validation's existing `incomplete_line_item` blocker covers it) — no second issue. Cost: none.
14. **`missing_<field>` is suppressed when a `review` finding on the same field already exists** (e.g. 1003's `due_date_unresolved` replaces `missing_due_date`). Cost: the blocker returns if the user wants unresolved dates to reject.
15. **`mode_switch_of` is deferred to P3-08** (no column exists); the semantic check skips runs with `retry_of` only. Cost: none until live mode.
16. **The 200-line cap counts invoice line items**, not source text lines. Cost: one comparison.
17. **The Net-N terms check is exact** (no tolerance). Several supplied invoices (1001, 1004, 1005, 1011, 1013) get a `terms_inconsistent` *warning*; warnings never change outcomes. Cost: noisy warnings.
18. **Table columns are read right-to-left** (amount, price, qty from the last numeric token), so item names may contain spaces, parentheses and digits; trailing text after the amount is a note only when the header has a `Notes` column. Cost: a note containing a number is misread (not in the corpus).

## Review Focus

1. **A labeled value that contains another label word** (`Due Date: 2026-02-01`, `Vendor: Due North Ltd.`) must not be split into two fields — only the *value* part of a line is searched for a second `Label:`. Test in Task 4.
2. **`O` next to non-numeric text** (`PO-20260115`, `26-Oct-2026`, `ORDER`) must not be "corrected", and a corrected amount that disagrees with qty × price must not be applied. Tests in Task 9.
3. **Upper-case or mixed-case extensions** (`.PDF`, `.Json`) route like lower-case ones; an empty file fails with a clear reason instead of producing a blank invoice. Tests in Task 2.
4. **An alternate format of a previously *failed* run is not a duplicate** and processes normally; a revision of a paid invoice never returns the old receipt as `paid_mock`. Tests in Task 11.
5. **Item names with digits** (`Model 3000 Bracket  2  $10.00  $20.00`) parse as one name, and a row with too few columns is `malformed_row`, never a shifted value. Tests in Task 4.

---

### Task 1: Contracts, dependencies, and parser dispatch

**Files:**
- Modify: `pyproject.toml`, `uv.lock`, `requirements.lock`
- Modify: `src/invoice_processing/codes.py`, `src/invoice_processing/schemas.py`
- Create: `src/invoice_processing/limits.py`, `src/invoice_processing/parsers/base.py`
- Modify: `src/invoice_processing/parsers/__init__.py`, `src/invoice_processing/parsers/txt.py`
- Modify: `src/invoice_processing/agents/state.py`, `src/invoice_processing/agents/ingestion.py`, `src/invoice_processing/service.py`
- Test: `tests/test_codes.py`, `tests/test_schemas.py`, `tests/test_agents.py`, `tests/test_parsers_dispatch.py` (new)

**Interfaces:**
- Produces:
  - New `FindingCode` members and severities:
    | Code | Severity |
    | --- | --- |
    | `ambiguous_normalization` | review |
    | `unparseable_value` | review |
    | `risk_signal_urgency` | info |
    | `due_date_unresolved` | review |
    | `ambiguous_date` | review |
    | `due_before_invoice_date` | warning |
    | `terms_inconsistent` | warning |
    | `unsupported_currency` | review |
    | `currency_conflict` | review |
    | `revision_after_payment` | review |
    | `version_conflict` | review |
    | `unrecognized_field` | info |
    | `duplicate_field` | review |
    | `malformed_row` | review |
    | `inconsistent_row_header` | blocker |
    Each gets a one-sentence `FINDING_DESCRIPTIONS` entry.
  - `schemas.ExtractionIssue.code: FindingCode` (was `str`).
  - `schemas.InvoiceDraft` new fields: `payment_terms_raw: str | None`, `notes_raw: str | None`, `tax_rate_fraction_raw: str | None` (fraction, e.g. `"0.08"`), `field_evidence: dict[str, list[EvidenceRef]]` (keys are the draft field names without `_raw`: `vendor`, `invoice_number`, `revision`, `invoice_date`, `due_date`, `currency`, `subtotal`, `tax_rate`, `tax`, `shipping`, `total`, `payment_terms`, `notes`), `normalization_events: list[NormalizationEvent]`. (`NormalizationEvent` moves above `InvoiceDraft`.)
  - `schemas.NormalizedInvoice` new fields: `payment_terms: str | None`, `notes: str | None`.
  - `schemas.ProcessingResult.error_message: str | None`.
  - `limits.Limits` — frozen dataclass `max_bytes: int = 10 * 1024 * 1024`, `max_pdf_pages: int = 25`, `max_lines: int = 200`; `limits.DEFAULT_LIMITS = Limits()`.
  - `parsers.base.ExtractionError(code: str, message: str)` with `.code`; `parsers.txt.ExtractionError` remains importable (re-export).
  - `parsers.ParsedDocument` — dataclass `draft: InvoiceDraft`, `extracted_text: str | None = None`.
  - `parsers.PARSER_VERSIONS: dict[SourceFormat, str]` — `txt: "txt-2"` now; later tasks add `json-1`, `csv-1`, `xml-1`, `pdf-1/pdfplumber-<version>`.
  - `parsers.parse_document(source: SourceDocument, data: bytes, limits: Limits) -> ParsedDocument` — dispatches on `source.format`; a format with no parser yet raises `ExtractionError("unsupported_format", ...)`.
  - `agents.state.Deps` gains `limits: Limits = DEFAULT_LIMITS` (last field, so existing `Deps(conn=, provider=, events=)` calls still work).
  - `service.process_invoice(path, mode, db_path, evaluation_date, events=None, limits: Limits = DEFAULT_LIMITS)`.
  - Ingestion node: calls `parse_document`; on `ExtractionError` sets `error_code=e.code` and `error_message=str(e)`; converts **every** `draft.issues` entry to a `ValidationFinding(code=issue.code, severity=DEFAULT_SEVERITY[issue.code], evidence=issue.evidence)`.
  - `normalize.normalize` puts `draft.normalization_events` first in `invoice.normalization_events` (so they are in the recorded version payload).
  - `service._result` fills `error_message` from state.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_codes.py (add)
from invoice_processing.codes import DEFAULT_SEVERITY, FINDING_DESCRIPTIONS, FindingCode, Severity

PHASE2 = {
    "ambiguous_normalization": Severity.review, "unparseable_value": Severity.review,
    "risk_signal_urgency": Severity.info, "due_date_unresolved": Severity.review,
    "ambiguous_date": Severity.review, "due_before_invoice_date": Severity.warning,
    "terms_inconsistent": Severity.warning, "unsupported_currency": Severity.review,
    "currency_conflict": Severity.review, "revision_after_payment": Severity.review,
    "version_conflict": Severity.review, "unrecognized_field": Severity.info,
    "duplicate_field": Severity.review, "malformed_row": Severity.review,
    "inconsistent_row_header": Severity.blocker,
}

def test_phase2_codes_and_severities():
    for name, severity in PHASE2.items():
        code = FindingCode(name)
        assert DEFAULT_SEVERITY[code] is severity
        assert FINDING_DESCRIPTIONS[code]

# tests/test_parsers_dispatch.py
import pytest
from invoice_processing.codes import SourceFormat
from invoice_processing.intake import read_source
from invoice_processing.limits import DEFAULT_LIMITS, Limits
from invoice_processing.parsers import PARSER_VERSIONS, ParsedDocument, parse_document
from invoice_processing.parsers.base import ExtractionError

def test_limits_defaults():
    assert DEFAULT_LIMITS == Limits(max_bytes=10 * 1024 * 1024, max_pdf_pages=25, max_lines=200)

def test_dispatch_txt():
    source, data = read_source("data/invoices/invoice_1001.txt")
    parsed = parse_document(source, data, DEFAULT_LIMITS)
    assert isinstance(parsed, ParsedDocument)
    assert parsed.draft.vendor_raw == "Widgets Inc."
    assert PARSER_VERSIONS[SourceFormat.txt] == source.parser_version == "txt-2"

def test_dispatch_without_parser_raises():
    source, data = read_source("data/invoices/invoice_1001.txt")
    with pytest.raises(ExtractionError) as e:
        parse_document(source.model_copy(update={"format": SourceFormat.xml}), data, DEFAULT_LIMITS)
    assert e.value.code == "unsupported_format"
```

Also add to `tests/test_agents.py`: an ingestion run whose draft (monkeypatched `parse_document`) has an issue with code `FindingCode.duplicate_field` produces a finding with severity `review`; and an ingestion run whose parser raises `ExtractionError("pdf_corrupt", "This PDF is damaged and cannot be read.")` ends with `status == failed`, `error_code == "pdf_corrupt"` and `error_message == "This PDF is damaged and cannot be read."`, and `service.process_invoice` returns `result.error_message` with that text.

- [ ] **Step 2: Run tests to verify they fail** — `uv run pytest tests/test_codes.py tests/test_parsers_dispatch.py tests/test_agents.py -q` → FAIL (`ImportError: limits`, missing codes).

- [ ] **Step 3: Implement** the interfaces above. Update `intake.py` to take `parser_version` from `parsers.PARSER_VERSIONS[SourceFormat.txt]` (intake routing itself changes in Task 2). Bump `parsers/txt.py` `PARSER_VERSION` to `"txt-2"`.

- [ ] **Step 4: Dependencies.** Add to `[project].dependencies`: `"defusedxml>=0.7,<0.8"`, `"langsmith>=0.14,<1"`, `"pdfplumber>=0.11,<0.12"`; add `"pypdf>=6,<7"` to the `dev` group. Run `uv lock && uv export --format requirements-txt --no-hashes > requirements.lock && uv sync`. If imports then fail with hidden `.pth` files, run `chflags -R nohidden .venv`.

- [ ] **Step 5: Run the full suite** — `uv run pytest -q` → all pass (Phase 1's 344 plus new); `uv run ruff check . && uv run ruff format --check .` clean.

- [ ] **Step 6: Commit** — `git commit -m "feat: Phase 2 contracts, limits, parser dispatch, and dependencies"`

---

### Task 2: Intake limits, format routing, and the line cap (P2-01 without PDF)

**Files:**
- Modify: `src/invoice_processing/intake.py`, `src/invoice_processing/agents/ingestion.py`, `src/invoice_processing/observability.py`
- Create: `tests/fixture_factory.py`
- Test: `tests/test_intake.py`, `tests/test_agents.py`, `tests/test_cli.py`, `tests/test_observability.py`

**Interfaces:**
- Consumes: `Limits`, `parsers.PARSER_VERSIONS`.
- Produces:
  - `intake.read_source(path: str | Path, limits: Limits = DEFAULT_LIMITS) -> tuple[SourceDocument, bytes]`, checks in this order:
    1. missing → `not_found`; not a regular file → `not_a_file` (unchanged);
    2. extension (case-insensitive) in `{.txt, .json, .csv, .xml, .pdf}` else `unsupported_format`;
    3. `stat().st_size > limits.max_bytes` → `file_too_large`, message `"File exceeds the 10 MiB limit."` (the number is `limits.max_bytes / 2**20` formatted with `:g`), checked **before** reading;
    4. read; `OSError` → `unreadable`, message `f"could not read file: {exc.strerror or exc}"`;
    5. zero bytes → `empty_file`, `"The file is empty."`;
    6. content sniff on the bytes after a UTF-8 BOM and leading ASCII whitespace: `.pdf` must start with `b"%PDF-"`; `.json` must start with `{` or `[`; `.xml` must start with `<`; `.txt`/`.csv` must not start with `b"%PDF-"` and must not contain `b"\x00"`. A mismatch → `format_mismatch`, message `f"The file is named {ext} but its content is not {FORMAT}."` (e.g. `"The file is named .json but its content is not JSON."`);
    7. `SourceDocument(format=..., parser_version=PARSER_VERSIONS.get(format, f"{format.value}-unavailable"))`.
  - `service.process_invoice` passes `limits` to `read_source`.
  - Ingestion: after parsing, `len(draft.lines) > deps.limits.max_lines` → `failed`, `error_code="too_many_lines"`, `error_message=f"The invoice has {n} lines; the limit is {max}."`.
  - `observability.format_summary` appends `error=<code>` and `reason="<error_message>"` when present.
  - `tests/fixture_factory.py`: `oversized_txt(dir: Path, size: int = 11 * 1024 * 1024) -> Path` (sparse via `truncate`), `json_containing_xml(dir: Path) -> Path`, `txt_with_lines(dir: Path, n: int) -> Path` (an INV-1001-style file with `n` item lines `WidgetA qty: 1 unit price: $1.00`). Task 8 adds the PDF builders.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_intake.py (add)
import pytest
from invoice_processing.codes import SourceFormat
from invoice_processing.intake import IntakeError, read_source
from invoice_processing.limits import Limits
from tests import fixture_factory as ff

def _code(path, **kw):
    with pytest.raises(IntakeError) as e:
        read_source(path, **kw)
    return e.value.code, str(e.value)

def test_oversized_file_rejected_before_read(tmp_path):
    assert _code(ff.oversized_txt(tmp_path)) == ("file_too_large", "File exceeds the 10 MiB limit.")

def test_limit_overridable(tmp_path):
    p = tmp_path / "a.txt"; p.write_text("INVOICE\n")
    assert _code(p, limits=Limits(max_bytes=4))[0] == "file_too_large"

def test_json_containing_xml_is_format_mismatch(tmp_path):
    code, msg = _code(ff.json_containing_xml(tmp_path))
    assert code == "format_mismatch" and msg == "The file is named .json but its content is not JSON."

@pytest.mark.parametrize("name,fmt", [("x.JSON", SourceFormat.json), ("x.Xml", SourceFormat.xml)])
def test_extension_case_insensitive(tmp_path, name, fmt):
    p = tmp_path / name; p.write_text("{}" if fmt is SourceFormat.json else "<a/>")
    assert read_source(p)[0].format is fmt

def test_empty_file(tmp_path):
    p = tmp_path / "e.txt"; p.write_bytes(b"")
    assert _code(p)[0] == "empty_file"

def test_pdf_header_required(tmp_path):
    p = tmp_path / "f.pdf"; p.write_text("hello")
    assert _code(p)[0] == "format_mismatch"

def test_all_supplied_files_pass_intake():
    from pathlib import Path
    for p in sorted(Path("data/invoices").iterdir()):
        source, _ = read_source(p)
        assert source.format.value == p.suffix[1:].lower()
```

Add: ingestion with `Limits(max_lines=2)` on `ff.txt_with_lines(tmp_path, 3)` (via `service.process_invoice(..., limits=Limits(max_lines=2))`) → `status == failed`, `errors == ["too_many_lines"]`, `error_message == "The invoice has 3 lines; the limit is 2."`, no payment; and a CLI test that the oversized file exits 2 with `file_too_large` on stderr and creates no run row. `format_summary` test: a failed result with `error_message` renders `error=too_many_lines reason="The invoice has 3 lines; the limit is 2."`.

- [ ] **Step 2: Run** `uv run pytest tests/test_intake.py tests/test_agents.py tests/test_cli.py tests/test_observability.py -q` → FAIL.
- [ ] **Step 3: Implement** as specified. Keep the existing intake error codes and messages for `not_found`/`not_a_file`.
- [ ] **Step 4: Run** the full suite → PASS; ruff clean.
- [ ] **Step 5: Commit** — `git commit -m "feat: intake size limit, format routing and sniffing, line cap"`

---

### Task 3: Text extractor — labeled layouts, label aliases, email bodies (P2-02)

**Files:**
- Create: `src/invoice_processing/parsers/text.py`
- Modify: `src/invoice_processing/parsers/txt.py` (decode, then delegate)
- Test: `tests/test_parser_text.py` (new), `tests/test_parser_txt.py`

**Interfaces:**
- Produces:
  - `parsers.text.parse_lines(source_id: str, lines: list[tuple[str, str]]) -> InvoiceDraft` — each tuple is `(location, raw_line)`; TXT passes `("line:N", text)`, PDF (Task 8) passes `("page:P,line:N", text)`.
  - `parsers.text.LABELS: dict[str, tuple[str, ...]]` — draft field → accepted label spellings (matched after casefold and whitespace collapse):
    | Field | Labels |
    | --- | --- |
    | `vendor` | Vendor, Vndr, From, Supplier |
    | `invoice_number` | Invoice Number, Invoice, Inv #, Inv No, Invoice No, Invoice # |
    | `invoice_date` | Date, Dt, Invoice Date |
    | `due_date` | Due Date, Due Dt, Due |
    | `currency` | Currency |
    | `subtotal` | Subtotal |
    | `tax` | Tax, Sales Tax (plus the pattern `Tax (N%)`, which also sets `tax_rate_raw = N`) |
    | `shipping` | Shipping |
    | `total` | Total, Total Amount, Amt, Grand Total |
    | `payment_terms` | Payment Terms, Pymnt Terms, Terms |
    | `notes` | Notes |
  - `ITEM_BLOCK_LABELS = ("Items", "Itms", "Items Ordered")`; `IGNORED_LABELS = ("Bill To", "To", "Attn", "Ship To")` (kept in `draft.evidence`, no issue).
  - `CANONICAL_LABELS = {"Vendor", "Invoice Number", "Date", "Due Date", "Currency", "Subtotal", "Tax", "Shipping", "Total", "Total Amount", "Payment Terms", "Notes", "Items"}` (casefold compare). Any other accepted spelling appends `NormalizationEvent(field=<field>, raw_value=<label as written>, normalized_value=<canonical label>, evidence=[ref], provenance="rule:label_alias")` to `draft.normalization_events`.
  - Rules, in order, per line:
    1. **Email header block:** if the first non-blank lines are `From:`/`To:`/`Cc:`/`Subject:`/`Date:` lines and a `From:` or `To:` value contains `@`, that block (up to the first blank line) is skipped and appended to `draft.evidence` only.
    2. Blank line → ends the item block and any notes continuation.
    3. A line that is exactly `INVOICE` (casefold) → skipped. A title `INVOICE #<value>` → `invoice_number_raw = <value>`, with a `rule:label_alias` event (raw `INVOICE #`, normalized `Invoice Number`).
    4. Inside an item block, item patterns (case-insensitive):
       - A `^(?P<name>.+?)\s+qty:\s*(?P<qty>\S+)\s+unit price:\s*(?P<price>\S+)$`
       - B `^(?P<name>.+?)\s+qty\s+(?P<qty>\S+)\s+@\s*(?P<price>\S+?)(\s+ea(ch)?)?$`
       - C `^-\s*(?P<name>.+?)\s+x(?P<qty>\S+)\s+(?P<price>\S+?)(\s+ea(ch)?)?$`
       A non-matching, non-label line inside the block → `unparsed_line` issue.
    5. `Label: value` lines: known field → set `<field>_raw` (value stripped), add the ref to `draft.evidence` and `draft.field_evidence[field]`. A second line for a field that is already set → `duplicate_field` issue (with both refs); the **first** value is kept. Item-block labels start the block; ignored labels → evidence only.
    6. `Notes:` value plus following non-blank, non-label lines are joined with a single space into `notes_raw`; each line's ref goes to `field_evidence["notes"]`.
    7. A line wholly in parentheses directly after the vendor line (`(formerly FastShip Ltd.)`) → evidence only (`field_evidence["vendor"]` gets it too); it never changes `vendor_raw`.
    8. Anything else → `unparsed_line` issue (info).

- [ ] **Step 1: Write the failing tests** (`tests/test_parser_text.py`; helper `draft(name) = parse_txt(*read_source(f"data/invoices/{name}"))`):

```python
def aliases(d):
    return {(e.field, e.raw_value) for e in d.normalization_events if e.provenance == "rule:label_alias"}

def test_1002_misspelled_labels():
    d = draft("invoice_1002.txt")
    assert (d.vendor_raw, d.invoice_number_raw) == ("Gadgets Co.", "1002")
    assert (d.invoice_date_raw, d.due_date_raw, d.total_raw) == ("Jan 30 2026", "2026-01-30", "$15,000.00")
    assert d.payment_terms_raw == "Net 30"
    assert [(x.raw_name, x.quantity_raw, x.unit_price_raw) for x in d.lines] == [("GadgetX", "20", "$750")]
    assert aliases(d) == {("vendor", "Vndr"), ("invoice_number", "Inv #"), ("invoice_date", "Dt"),
                          ("due_date", "Due Dt"), ("total", "Amt"), ("payment_terms", "Pymnt Terms")}
    assert d.field_evidence["vendor"][0].location == "line:3"

def test_1003_notes_and_relative_due_date():
    d = draft("invoice_1003.txt")
    assert [(x.raw_name, x.quantity_raw, x.unit_price_raw) for x in d.lines] == [("FakeItem", "100", "$1,000.00")]
    assert d.total_raw == "$100,000.00" and d.due_date_raw == "yesterday"
    assert d.notes_raw == "URGENT - Pay immediately to avoid penalties!!! Wire transfer preferred."
    assert d.payment_terms_raw == "Immediate"

def test_1008_email_body():
    d = draft("invoice_1008.txt")
    assert (d.vendor_raw, d.invoice_number_raw, d.total_raw) == ("NoProd Industries", "INV-1008", "$9,900.00")
    assert [(x.raw_name, x.quantity_raw, x.unit_price_raw) for x in d.lines] == [
        ("SuperGizmo", "12", "$400.00"), ("MegaSprocket", "6", "$850.00")]
    assert all("@" not in (e.snippet or "") for e in d.field_evidence["vendor"])

def test_from_without_address_is_vendor():
    d = parse_lines("s", [("line:1", "FROM:  QuickShip Distributers"), ("line:2", "  (formerly FastShip Ltd.)")])
    assert d.vendor_raw == "QuickShip Distributers"
    assert [e.location for e in d.field_evidence["vendor"]] == ["line:1", "line:2"]
    assert d.issues == []

def test_repeated_label_is_duplicate_field_first_wins():
    d = parse_lines("s", [("line:1", "Vendor: A Co."), ("line:2", "Vendor: B Co.")])
    assert d.vendor_raw == "A Co."
    assert [i.code for i in d.issues] == ["duplicate_field"]

def test_every_value_has_line_evidence():
    for name in ("invoice_1002.txt", "invoice_1003.txt", "invoice_1008.txt"):
        d = draft(name)
        assert all(x.evidence[0].location.startswith("line:") for x in d.lines)
        assert all(refs and refs[0].location.startswith("line:") for refs in d.field_evidence.values())
```

The existing `tests/test_parser_txt.py` (1001, CRLF/BOM, unparsed lines) must still pass unchanged, and 1001 has no `rule:label_alias` events.

- [ ] **Step 2: Run** `uv run pytest tests/test_parser_text.py tests/test_parser_txt.py -q` → FAIL.
- [ ] **Step 3: Implement** `parsers/text.py`; reduce `parsers/txt.py` to decoding (`utf-8-sig`, strict; `txt_decode_error` unchanged) plus `parse_lines(source.source_id, [(f"line:{n}", line) ...])`.
- [ ] **Step 4: Run** the full suite → PASS; ruff clean.
- [ ] **Step 5: Commit** — `git commit -m "feat: labeled TXT layouts with label aliases, email headers and notes"`

---

### Task 4: Text extractor — column tables, footers, two-field header lines (P2-03)

**Files:**
- Modify: `src/invoice_processing/parsers/text.py`
- Test: `tests/test_parser_text.py`

**Interfaces:**
- Consumes: `parse_lines` from Task 3.
- Produces (inside `parse_lines`):
  - **Table header:** a line whose casefolded, whitespace-collapsed text matches `^(item|description)\s+(qty|quantity)\s+(unit price|rate|price)\s+(amount|total|line total)(\s+notes)?$` starts table mode (header ref kept as evidence). Only this column order is supported.
  - **Separator lines** matching `^[\s\-=_]+$` are skipped everywhere (no issue).
  - **Table rows:** tokens = `line.split()`; a numeric token matches `^-?\$?[\dO][\dO,]*(\.[\dO]+)?$` and contains at least one digit (raw `O` is kept for Task 9). Let `k` be the index of the last numeric token: amount = `tokens[k]`, price = `tokens[k-1]`, qty = `tokens[k-2]` (all must be numeric), name = `" ".join(tokens[:k-2])` (must be non-empty), note = `" ".join(tokens[k+1:])` or `None`. A note when the header has no `Notes` column, or any shortfall → `malformed_row` issue (no line emitted).
  - Table mode ends at a blank line or a line containing a known `Label:`; footer labels then go through the Task 3 label rules (`Subtotal`, `Tax (N%)`, `Sales Tax`, `Shipping`, `Total`, `Grand Total`).
  - **Two fields on one line:** after splitting `Label: value`, the *value* part (never the label part) is searched for `\s+(?=(<any LABELS spelling>)\s*:)`; each further segment is handled as its own labeled line with the same location. Not applied when the first label is `Notes`.

- [ ] **Step 1: Write the failing tests**

```python
def rows(d):
    return [(x.raw_name, x.quantity_raw, x.unit_price_raw, x.line_total_raw) for x in d.lines]

def test_1010_table_and_footer():
    d = draft("invoice_1010.txt")
    assert d.invoice_number_raw == "INV-1010" and d.vendor_raw == "Consolidated Materials Group"
    assert rows(d) == [("WidgetA", "8", "$250.00", "$2,000.00"), ("WidgetB", "4", "$500.00", "$2,000.00"),
                       ("GadgetX", "2", "$750.00", "$1,500.00"),
                       ("WidgetA (rush order)", "4", "$300.00", "$1,200.00")]
    assert (d.subtotal_raw, d.tax_raw, d.tax_rate_raw, d.shipping_raw, d.total_raw) == (
        "$6,700.00", "$335.00", None, "$150.00", "$7,185.00")

def test_1011_txt():
    d = draft("invoice_1011.txt")
    assert [r[:2] for r in rows(d)] == [("WidgetA", "6"), ("WidgetB", "3")]
    assert (d.subtotal_raw, d.tax_rate_raw, d.tax_raw, d.total_raw) == ("$3,000.00", "0", "$0.00", "$3,000.00")

def test_1012_raw_tokens_preserved():
    d = draft("invoice_1012.txt")
    assert d.vendor_raw == "QuickShip Distributers" and d.invoice_number_raw == "INV 1012"
    assert d.invoice_date_raw == "26-Jan-2O26"
    assert rows(d) == [("Widget A", "12", "$250", "$3,000.00"), ("WidgetB", "7", "$500", "$3,500.O0"),
                       ("Gadget X", "4", "$750", "$3,000.00")]
    assert (d.subtotal_raw, d.tax_rate_raw, d.tax_raw, d.total_raw) == ("$9,500.00", "5", "$475.00", "$9,975.00")
    assert d.notes_raw == "Ref PO-20260115. Deliver to warehouse dock B. Contact Jim at ext 4421 with questions."
    assert d.payment_terms_raw == "Net 30"

TABLE = [("line:1", "Item  Qty  Unit Price  Amount")]

def test_row_with_missing_column_is_malformed():
    d = parse_lines("s", TABLE + [("line:2", "WidgetA  6  $1,500.00")])
    assert d.lines == [] and [i.code for i in d.issues] == ["malformed_row"]

def test_item_name_with_digits():
    d = parse_lines("s", TABLE + [("line:2", "Model 3000 Bracket  2  $10.00  $20.00")])
    assert rows(d) == [("Model 3000 Bracket", "2", "$10.00", "$20.00")]

def test_two_fields_on_one_line():
    d = parse_lines("s", [("line:1", "Invoice: INV-9      Date: 2026-01-24"),
                          ("line:2", "Vendor: Atlas Supply Due: 2026-03-24")])
    assert (d.invoice_number_raw, d.invoice_date_raw) == ("INV-9", "2026-01-24")
    assert (d.vendor_raw, d.due_date_raw) == ("Atlas Supply", "2026-03-24")

def test_label_words_inside_values_do_not_split():
    d = parse_lines("s", [("line:1", "Due Date: 2026-02-01"), ("line:2", "Vendor: Due North Ltd.")])
    assert (d.due_date_raw, d.vendor_raw) == ("2026-02-01", "Due North Ltd.")
    assert d.invoice_date_raw is None
```

- [ ] **Step 2: Run** `uv run pytest tests/test_parser_text.py -q` → new tests FAIL.
- [ ] **Step 3: Implement** in `parsers/text.py`.
- [ ] **Step 4: Run** the full suite → PASS; ruff clean.
- [ ] **Step 5: Commit** — `git commit -m "feat: TXT column tables, footer totals and two-field header lines"`

---

### Task 5: JSON parser (P2-04)

**Files:**
- Create: `src/invoice_processing/parsers/json_parser.py`
- Modify: `src/invoice_processing/parsers/__init__.py` (register `SourceFormat.json`, version `"json-1"`)
- Test: `tests/test_parser_json.py`

**Interfaces:**
- Produces: `parsers.json_parser.parse_json(source: SourceDocument, data: bytes) -> InvoiceDraft`.
  - `json.loads(text, parse_float=Decimal, parse_int=Decimal, object_pairs_hook=...)`; invalid UTF-8 or JSON → `ExtractionError("json_invalid", "The JSON file could not be parsed: <reason>.")`; top level not an object → `ExtractionError("json_invalid", ...)`.
  - Mapping (JSON path → draft field): `$.invoice_number`, `$.revision`, `$.vendor` (a string) or `$.vendor.name`, `$.date` or `$.invoice_date`, `$.due_date`, `$.currency`, `$.subtotal`, `$.tax_rate` → `tax_rate_fraction_raw`, `$.tax_amount` or `$.tax` → `tax_raw`, `$.shipping`, `$.total`, `$.payment_terms`, `$.notes`; `$.line_items[i]` → `item`, `quantity`, `unit_price`, `amount` → `line_total_raw`, `note`.
  - Scalars become raw strings with `str()` (Decimal keeps `"250.00"`, `"-5"`); `""` and `null` are absent (`None`), not values; booleans, lists or objects where a scalar is expected → that field absent plus a `malformed_row` issue citing the path.
  - Evidence location is the JSON path (`$.line_items[3].quantity`), snippet the raw value; `field_evidence` filled.
  - Unknown top-level keys → `unrecognized_field` issue each (known: the keys above plus `vendor.address`, which is evidence only).
  - Duplicate keys in any object → `duplicate_field` issue; the first value wins.
  - `$.line_items` not a list → `malformed_row` issue, no lines.

- [ ] **Step 1: Write the failing tests**

```python
def d(name): return parse_json(*read_source(f"data/invoices/{name}"))

def test_all_json_fixtures_parse():
    for n in ("1004", "1004_revised", "1005", "1009", "1013", "1016"):
        d(f"invoice_{n}.json")

def test_1013_lines_notes_and_exact_total():
    x = d("invoice_1013.json")
    assert len(x.lines) == 8 and x.total_raw == "22562.80"
    assert [l.note for l in x.lines] == [None, None, None, "Volume discount", "Volume discount",
                                         "Expedited", "Replacement", "Sample"]
    assert x.lines[3].evidence[0].location.startswith("$.line_items[3]")
    assert x.tax_rate_fraction_raw == "0.07" and x.tax_rate_raw is None

def test_revision():
    assert d("invoice_1004_revised.json").revision_raw == "R1"
    assert d("invoice_1004.json").revision_raw is None

def test_1009_missing_and_invalid_values_kept():
    x = d("invoice_1009.json")
    assert x.vendor_raw is None and x.due_date_raw is None and x.payment_terms_raw is None
    assert x.lines[0].quantity_raw == "-5" and x.total_raw == "-250.00"

def test_duplicate_and_unknown_keys(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"invoice_number": "A", "invoice_number": "B", "po": "X"}')
    x = parse_json(*read_source(p))
    assert x.invoice_number_raw == "A"
    assert sorted(i.code for i in x.issues) == ["duplicate_field", "unrecognized_field"]

def test_invalid_json(tmp_path):
    p = tmp_path / "b.json"; p.write_text("{nope")
    with pytest.raises(ExtractionError) as e: parse_json(*read_source(p))
    assert e.value.code == "json_invalid"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_parser_json.py -q` → FAIL.
- [ ] **Step 3: Implement**; register in `parse_document`.
- [ ] **Step 4: Run** the full suite → PASS; ruff clean.
- [ ] **Step 5: Commit** — `git commit -m "feat: JSON invoice parser with exact decimals and path evidence"`

---

### Task 6: CSV parsers — field/value and row table (P2-05)

**Files:**
- Create: `src/invoice_processing/parsers/csv_parser.py`
- Modify: `src/invoice_processing/parsers/__init__.py` (register `SourceFormat.csv`, `"csv-1"`)
- Test: `tests/test_parser_csv.py`

**Interfaces:**
- Produces: `parsers.csv_parser.parse_csv(source: SourceDocument, data: bytes) -> InvoiceDraft`. Decode `utf-8-sig` strictly (`csv_decode_error`); read with `csv.reader`.
  - **Field/value layout:** header (casefolded) `["field", "value"]`. Fields: `invoice_number`, `vendor`, `date`/`invoice_date`, `due_date`, `currency`, `subtotal`, `tax`, `tax_rate` (fraction → `tax_rate_fraction_raw`), `shipping`, `total`, `payment_terms`, `notes`, `revision`; line fields `item` (opens a new line), `quantity`, `unit_price`, `amount` (line total), `note`. A line field with no open line → `malformed_row` issue. A new `item` while the current line lacks quantity or unit price closes that line as-is (validation reports `incomplete_line_item`); values are never carried over to the next item. A repeated header field → `duplicate_field`, first wins. Unknown field → `unrecognized_field`.
  - **Row-table layout:** header (casefolded, stripped) equals `invoice number, vendor, date, due date, item, qty, unit price, line total` (an extra trailing `currency` column is allowed). Data rows have a non-empty `Item`. Invoice-level columns must be identical on every data row; any difference → `inconsistent_row_header` issue (blocker) citing both rows, first value kept. Footer rows (all leading cells empty) carry the label in the `Unit Price` column and the value in `Line Total`: `Subtotal:`, `Tax (N%):` (sets `tax_rate_raw = N` and `tax_raw`), `Tax:`, `Shipping:`, `Total:`; unknown footer label → `unparsed_line`.
  - Any other header → `ExtractionError("unsupported_csv_layout", "This CSV layout is not supported.")`.
  - Evidence location `row:<reader.line_num>` or `row:<n>,col:<Header>`; row order preserved.

- [ ] **Step 1: Write the failing tests**

```python
def lines(x): return [(l.raw_name, l.quantity_raw, l.unit_price_raw) for l in x.lines]

def test_1006_field_value():
    x = parse_csv(*read_source("data/invoices/invoice_1006.csv"))
    assert lines(x) == [("WidgetA", "5", "250.00"), ("WidgetB", "3", "500.00")]
    assert (x.subtotal_raw, x.tax_raw, x.total_raw, x.payment_terms_raw) == ("2750.00", "0.00", "2750.00", "Net 15")

def test_1007_row_table():
    x = parse_csv(*read_source("data/invoices/invoice_1007.csv"))
    assert len(x.lines) == 3 and (x.invoice_date_raw, x.due_date_raw) == ("01/28/2026", "02/28/2026")
    assert (x.subtotal_raw, x.tax_rate_raw, x.tax_raw, x.total_raw) == ("14750.00", "6", "885.00", "15525.00")
    assert x.lines[0].line_total_raw == "5000.00"
    assert x.issues == []

def test_1015_row_table():
    x = parse_csv(*read_source("data/invoices/invoice_1015.csv"))
    assert len(x.lines) == 3 and (x.subtotal_raw, x.tax_raw, x.total_raw) == ("6500.00", "0.00", "6500.00")

def test_rows_disagree_on_vendor(tmp_path):
    p = tmp_path / "v.csv"
    p.write_text("Invoice Number,Vendor,Date,Due Date,Item,Qty,Unit Price,Line Total\n"
                 "INV-1,A Co,2026-01-01,2026-02-01,WidgetA,1,1.00,1.00\n"
                 "INV-1,B Co,2026-01-01,2026-02-01,WidgetB,1,1.00,1.00\n")
    x = parse_csv(*read_source(p))
    assert x.vendor_raw == "A Co" and "inconsistent_row_header" in [i.code for i in x.issues]

def test_incomplete_group_not_merged(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("field,value\nitem,WidgetA\nquantity,5\nitem,WidgetB\nquantity,3\nunit_price,500.00\n")
    x = parse_csv(*read_source(p))
    assert lines(x) == [("WidgetA", "5", None), ("WidgetB", "3", "500.00")]

def test_unknown_layout(tmp_path):
    p = tmp_path / "u.csv"; p.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ExtractionError) as e: parse_csv(*read_source(p))
    assert e.value.code == "unsupported_csv_layout"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_parser_csv.py -q` → FAIL.
- [ ] **Step 3: Implement**; register.
- [ ] **Step 4: Run** the full suite → PASS; ruff clean.
- [ ] **Step 5: Commit** — `git commit -m "feat: CSV parsers for field/value and row-table layouts"`

---

### Task 7: Hardened XML parser (P2-06)

**Files:**
- Create: `src/invoice_processing/parsers/xml_parser.py`
- Modify: `src/invoice_processing/parsers/__init__.py` (register `SourceFormat.xml`, `"xml-1"`)
- Test: `tests/test_parser_xml.py`

**Interfaces:**
- Produces: `parsers.xml_parser.parse_xml(source: SourceDocument, data: bytes) -> InvoiceDraft`.
  - `defusedxml.ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)`. `DTDForbidden`, `EntitiesForbidden`, `ExternalReferenceForbidden` → `ExtractionError("xml_forbidden_construct", "This XML uses DTDs or entities, which are not allowed.")`; `ParseError` → `ExtractionError("xml_invalid", ...)`. Root must be `<invoice>` else `xml_invalid`.
  - Paths: `header/{invoice_number, revision, vendor, date, due_date, currency}`, `line_items/item/{name, quantity, unit_price, amount, note}`, `totals/{subtotal, tax_rate (fraction → tax_rate_fraction_raw), tax_amount, shipping, total}`, `payment_terms`, `notes` (each also accepted directly under the root).
  - Text is stripped; empty text is absent. A repeated singleton → `duplicate_field` (first wins). Unknown elements → `unrecognized_field`.
  - Evidence location is an element path with 1-based indexes: `/invoice/line_items/item[2]/quantity`.

- [ ] **Step 1: Write the failing tests**

```python
def test_1014():
    x = parse_xml(*read_source("data/invoices/invoice_1014.xml"))
    assert (x.vendor_raw, x.currency_raw) == ("TechParts International", "EUR")
    assert [(l.raw_name, l.quantity_raw, l.unit_price_raw) for l in x.lines] == [
        ("WidgetA", "4", "225.00"), ("WidgetB", "6", "475.00")]
    assert (x.subtotal_raw, x.tax_rate_fraction_raw, x.tax_raw, x.total_raw) == ("3750.00", "0.10", "375.00", "4125.00")
    assert x.lines[1].evidence[0].location == "/invoice/line_items/item[2]"

BILLION_LAUGHS = b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><invoice>&b;</invoice>'
XXE = b'<?xml version="1.0"?><!DOCTYPE i [<!ENTITY x SYSTEM "file:///etc/passwd">]><invoice>&x;</invoice>'

@pytest.mark.parametrize("payload", [BILLION_LAUGHS, XXE])
def test_forbidden_constructs(tmp_path, payload):
    p = tmp_path / "x.xml"; p.write_bytes(payload)
    with pytest.raises(ExtractionError) as e: parse_xml(*read_source(p))
    assert e.value.code == "xml_forbidden_construct"
```

Also: a repeated `<vendor>` yields `duplicate_field`; malformed XML yields `xml_invalid`. The autouse network guard stays active.

- [ ] **Step 2: Run** `uv run pytest tests/test_parser_xml.py -q` → FAIL.
- [ ] **Step 3: Implement**; register.
- [ ] **Step 4: Run** the full suite → PASS; ruff clean.
- [ ] **Step 5: Commit** — `git commit -m "feat: defusedxml invoice parser refusing DTDs and entities"`

---

### Task 8: PDF text extraction and preflight (P2-07, PDF part of P2-01)

**Files:**
- Create: `src/invoice_processing/parsers/pdf.py`, `tests/fixtures/pdf_text/invoice_1011.txt`, `…_1012.txt`, `…_1013.txt`
- Modify: `src/invoice_processing/parsers/__init__.py` (register `SourceFormat.pdf`, version `f"pdf-1/pdfplumber-{pdfplumber.__version__}"`), `src/invoice_processing/ledger.py` (`set_extracted_text`), `src/invoice_processing/agents/ingestion.py`, `tests/fixture_factory.py`, `docs/tickets/P2-07-pdf-text-extraction.md`
- Test: `tests/test_parser_pdf.py`

**Interfaces:**
- Consumes: `parse_lines` (Tasks 3–4), `Limits`.
- Produces:
  - `parsers.pdf.extract_pdf_text(data: bytes, limits: Limits) -> list[str]` — one string per page, `page.extract_text(layout=True)` with each line right-stripped and blank lines removed. Preflight, in order:
    - opening fails with a password error (pdfplumber's `PdfminerException` wrapping pdfminer's `PDFPasswordIncorrect`) → `ExtractionError("pdf_encrypted", "This PDF is password-protected and cannot be read.")`;
    - any other open or parse failure → `ExtractionError("pdf_corrupt", "This PDF is damaged and cannot be read.")`;
    - `len(pdf.pages) > limits.max_pdf_pages` → `ExtractionError("too_many_pages", f"The PDF has {n} pages; the limit is {max}.")`, checked before extracting text;
    - no non-whitespace text on any page → `ExtractionError("pdf_needs_ocr", "This PDF needs OCR, which this prototype does not support.")`.
  - `parsers.pdf.parse_pdf(source, data, limits) -> ParsedDocument` — `parse_lines(source_id, [(f"page:{p},line:{n}", line) ...])`, `extracted_text = "\n\f\n".join(pages)`.
  - `ledger.set_extracted_text(conn, source_id: str, text: str) -> None` (only when the column is NULL); the ingestion node calls it when `parsed.extracted_text` is not None. The text is never logged.
  - `tests/fixture_factory.py` adds (using `pypdf`): `pdf_pages(dir, n)` (n blank pages), `image_only_pdf(dir)` (one blank page, no text), `encrypted_pdf(dir, user_password="secret")` (1011 PDF encrypted with RC4-128), `truncated_pdf(dir)` (first 600 bytes of 1011 PDF).

- [ ] **Step 1: Write the snapshot files** by running `extract_pdf_text` once on each committed PDF *after* Step 3 and writing the joined pages to `tests/fixtures/pdf_text/<stem>.txt`; inspect them by eye against the ticket's `pdftotext` reading (same lines; pdfplumber drops blank lines and uses different column spacing). Record that difference in the P2-07 ticket under a new "Extraction notes" heading.

- [ ] **Step 2: Write the failing tests**

```python
def pdf(name): return parse_document(*read_source(f"data/invoices/{name}"), DEFAULT_LIMITS)

@pytest.mark.parametrize("stem", ["invoice_1011", "invoice_1012", "invoice_1013"])
def test_snapshot(stem):
    pages = extract_pdf_text(Path(f"data/invoices/{stem}.pdf").read_bytes(), DEFAULT_LIMITS)
    assert "\n\f\n".join(pages) == Path(f"tests/fixtures/pdf_text/{stem}.txt").read_text()

def test_1011_pdf_total_only():
    d = pdf("invoice_1011.pdf").draft
    assert [(l.raw_name, l.quantity_raw) for l in d.lines] == [("WidgetA", "6"), ("WidgetB", "3")]
    assert d.total_raw == "$3,000.00" and d.subtotal_raw is None and d.tax_raw is None
    assert d.lines[0].evidence[0].location.startswith("page:1,line:")

def test_1012_pdf_matches_txt():
    t = parse_txt(*read_source("data/invoices/invoice_1012.txt"))
    p = pdf("invoice_1012.pdf").draft
    fields = ("vendor_raw", "invoice_number_raw", "invoice_date_raw", "due_date_raw", "subtotal_raw",
              "tax_rate_raw", "tax_raw", "total_raw", "payment_terms_raw", "notes_raw")
    assert [getattr(p, f) for f in fields] == [getattr(t, f) for f in fields]
    key = lambda d: [(l.raw_name, l.quantity_raw, l.unit_price_raw, l.line_total_raw) for l in d.lines]
    assert key(p) == key(t)

def test_1013_pdf():
    d = pdf("invoice_1013.pdf").draft
    assert len(d.lines) == 8 and d.invoice_number_raw == "INV-1013"
    assert (d.invoice_date_raw, d.due_date_raw) == ("2026-01-24", "2026-03-24")
    assert [l.note for l in d.lines][3:] == ["Volume discount", "Volume discount", "Expedited", "Replacement", "Sample"]
    assert (d.subtotal_raw, d.tax_rate_raw, d.tax_raw, d.total_raw) == ("$21,040.00", "7", "$1,472.80", "$22,562.80")
    assert d.currency_raw is None and d.payment_terms_raw == "Net 60"

@pytest.mark.parametrize("build,code", [
    (lambda d: ff.pdf_pages(d, 26), "too_many_pages"), (ff.image_only_pdf, "pdf_needs_ocr"),
    (ff.encrypted_pdf, "pdf_encrypted"), (ff.truncated_pdf, "pdf_corrupt")])
def test_preflight_failures_fail_the_run_without_payment(tmp_path, build, code):
    result = process_invoice(build(tmp_path), ExecutionMode.offline, tmp_path / "db.sqlite", date(2026, 1, 31))
    assert result.status is RunStatus.failed and result.errors == [code] and result.error_message
    assert result.receipt is None

def test_empty_password_encryption_is_readable(tmp_path):
    d = parse_document(*read_source(ff.encrypted_pdf(tmp_path, user_password="")), DEFAULT_LIMITS).draft
    assert d.total_raw == "$3,000.00"

def test_page_limit_overridable(tmp_path):
    with pytest.raises(ExtractionError) as e:
        extract_pdf_text(Path("data/invoices/invoice_1011.pdf").read_bytes(), Limits(max_pdf_pages=0))
    assert e.value.code == "too_many_pages"
```

Note: `process_invoice` needs a seeded database; use the existing seeding helper the service tests use. Also assert `sources.extracted_text` is set for a processed 1011 PDF and that no audit payload or JSONL line contains `"Summit Manufacturing Co."` alongside `"Unit Price"` (the full text is not logged).

- [ ] **Step 3: Implement**; register.
- [ ] **Step 4: Run** the full suite → PASS; ruff clean.
- [ ] **Step 5: Commit** — `git commit -m "feat: pdfplumber text extraction with preflight and snapshots"`

---

### Task 9: Evidence-backed normalization — amounts, OCR digits, items, identity (P2-08)

**Files:**
- Modify: `src/invoice_processing/normalize.py`, `src/invoice_processing/storage.py` (`SCHEMA_VERSION = 4`, `inventory_items`), `src/invoice_processing/agents/ingestion.py`, `src/invoice_processing/agents/validation.py`, `src/invoice_processing/validation.py`
- Test: `tests/test_normalize.py`, `tests/test_storage.py`, `tests/test_validation_fields.py`

**Interfaces:**
- Consumes: drafts from Tasks 3–8.
- Produces:
  - `normalize.normalize(draft: InvoiceDraft, known_items: Collection[str] = ()) -> tuple[NormalizedInvoice, list[ValidationFinding]]`. The ingestion node passes `storage.inventory_items(deps.conn)`.
  - `storage.inventory_items(conn) -> list[str]` (all inventory names, sorted).
  - `normalize.parse_amount(raw: str) -> Decimal` — strips one leading currency symbol (`$`, `€`, `£`) and an optional `-` before or after it; accepts `^\d+(\.\d+)?$` or correctly grouped `^\d{1,3}(,\d{3})+(\.\d+)?$`; anything else (`1,2,3`, `12,34.00`) raises `ValueError`.
  - `normalize.fix_ocr_digits(raw: str) -> str | None` — replaces `O` with `0` only where the `O` is adjacent to a digit, `.` or `,` (`(?<=[\d.,])O|O(?=[\d.,])`); returns `None` if nothing changed. The caller applies it only to amount, quantity and date fields, and only if the result then parses.
  - `normalize.invoice_number_key(number: str) -> str` — uppercase, remove spaces and `-_/#.`, then strip a leading `INV` that is followed by a digit: `"INV 1012"`, `"INV-1012"` → `"1012"`; `"1002"` → `"1002"`.
  - `normalize.vendor_key` unchanged (casefold, collapse whitespace).
  - Rules and their events (`provenance`):
    - `rule:ocr_digit` — per corrected field; a corrected **line total** is applied only if quantity and unit price both parse and `corrected == quantity * unit_price`; otherwise the correction is not applied (`line_total = None`) and an `ambiguous_normalization` finding (field `lines[i].line_total`, line evidence) is emitted. If quantity or price is missing, the correction is applied.
    - `rule:item_spacing` — `raw_name` whose whitespace-removed form equals a known item exactly (case-sensitive): `Widget A` → `WidgetA`.
    - `rule:item_qualifier` — `^(?P<base>.+?)\s*\((?P<q>[^()]+)\)$` where `base` (after the spacing rule) is a known item: item = base, `q` is appended to the line note (`"; "`-joined). No other item changes; `WidgetC`, `SuperGizmo`, `MegaSprocket` stay as written.
    - `rule:invoice_number_format` — whenever the key differs from the stripped display value; `invoice_number` keeps the source text.
    - `rule:unparseable` (existing) now also emits an `unparseable_value` finding (review) with `field` set and the field's own evidence from `draft.field_evidence` (carry-over: no longer all draft evidence).
  - `NormalizedInvoice.payment_terms`/`notes` copied from the draft (stripped, blank → `None`); `tax_rate` from `tax_rate_raw` (percent ÷ 100) or `tax_rate_fraction_raw` (as is).
  - `validation.check_required_fields(invoice, *, unresolved: Collection[str] = ())` — skips `missing_<field>` for fields in `unresolved`. The validation node passes the `field` of every earlier finding whose severity is `review`.
  - `storage.SCHEMA_VERSION = 4` (no DDL change; see Decision 11). Update `docs/development.md` with one line: a Phase 1 `inventory.db` must be deleted and re-seeded.

- [ ] **Step 1: Write the failing tests**

```python
ITEMS = ("WidgetA", "WidgetB", "GadgetX", "FakeItem")
def norm(name):
    src = read_source(f"data/invoices/{name}")
    return normalize(parse_document(*src, DEFAULT_LIMITS).draft, ITEMS)
def rules(inv): return [e.provenance for e in inv.normalization_events]

def test_1010_qualifier():
    inv, _ = norm("invoice_1010.txt")
    assert [(l.item, l.quantity) for l in inv.lines] == [
        ("WidgetA", Decimal(8)), ("WidgetB", Decimal(4)), ("GadgetX", Decimal(2)), ("WidgetA", Decimal(4))]
    assert inv.lines[3].note == "rush order" and "rule:item_qualifier" in rules(inv)
    assert aggregate_quantities(inv.lines)["WidgetA"].quantity == 12

@pytest.mark.parametrize("name", ["invoice_1012.txt", "invoice_1012.pdf"])
def test_1012_spacing_ocr_identity(name):
    inv, findings = norm(name)
    assert [(l.item, l.quantity) for l in inv.lines] == [
        ("WidgetA", Decimal(12)), ("WidgetB", Decimal(7)), ("GadgetX", Decimal(4))]
    assert inv.lines[1].line_total == Decimal("3500.00")
    assert inv.invoice_number == "INV 1012" and inv.invoice_number_key == "1012"
    assert rules(inv).count("rule:item_spacing") == 2
    assert "rule:ocr_digit" in rules(inv) and "rule:invoice_number_format" in rules(inv)
    assert inv.vendor_key == "quickship distributers"
    assert not [f for f in findings if f.code is FindingCode.ambiguous_normalization]

def test_1016_widgetc_not_mapped():
    inv, _ = norm("invoice_1016.json")
    assert inv.lines[2].item == "WidgetC"

def test_ocr_amount_disagreeing_with_qty_price_is_not_applied():
    d = parse_lines("s", [("line:1", "Item  Qty  Unit Price  Amount"),
                          ("line:2", "WidgetB  6  $500.00  $3,5O0.00")])
    inv, findings = normalize(d, ITEMS)
    assert inv.lines[0].line_total is None
    assert [f.code for f in findings if f.severity is Severity.review] == [FindingCode.ambiguous_normalization]

@pytest.mark.parametrize("raw", ["PO-20260115", "26-Oct-2026", "ORDER 5", "$3,500.00"])
def test_ocr_leaves_non_numeric_o_alone(raw):
    assert fix_ocr_digits(raw) is None

@pytest.mark.parametrize("raw,expected", [("2O26", "2026"), ("$3,500.O0", "$3,500.00")])
def test_ocr_fixes_digit_tokens(raw, expected):
    assert fix_ocr_digits(raw) == expected

@pytest.mark.parametrize("raw", ["1,2,3", "12,34.00", "$1,00"])
def test_parse_amount_rejects_misplaced_commas(raw):
    with pytest.raises(ValueError): parse_amount(raw)

@pytest.mark.parametrize("raw,key", [("INV 1012", "1012"), ("INV-1012", "1012"), ("1002", "1002"), ("inv-1001", "1001")])
def test_invoice_number_key(raw, key):
    assert invoice_number_key(raw) == key

def test_unparseable_value_cites_its_own_line():
    d = parse_lines("s", [("line:1", "Vendor: A"), ("line:2", "Total: $abc")])
    _, findings = normalize(d, ITEMS)
    f = next(f for f in findings if f.code is FindingCode.unparseable_value)
    assert f.field == "total" and [e.location for e in f.evidence] == ["line:2"]
```

Plus: `check_required_fields(inv, unresolved={"total"})` omits `missing_total`; `init_schema` refuses a `user_version = 3` database with `SchemaVersionError`; `inventory_items` returns the four seed names.

- [ ] **Step 2: Run** `uv run pytest tests/test_normalize.py tests/test_storage.py tests/test_validation_fields.py -q` → FAIL.
- [ ] **Step 3: Implement.** Existing Phase 1 normalize tests that assert `invoice_number_key == "INV-1001"` change to `"1001"`; fix them in this task and say so in the report.
- [ ] **Step 4: Run** the full suite → PASS; ruff clean.
- [ ] **Step 5: Commit** — `git commit -m "feat: evidence-backed normalization for amounts, OCR digits, items and identity keys"`

---

### Task 10: Dates, currency, payment terms, and urgency signals (P2-09)

**Files:**
- Create: `src/invoice_processing/dates.py`
- Modify: `src/invoice_processing/normalize.py`
- Test: `tests/test_dates.py` (new), `tests/test_normalize.py`

**Interfaces:**
- Consumes: `fix_ocr_digits`, field evidence (Task 9).
- Produces:
  - `dates.parse_date(raw: str) -> date`, raising `dates.RelativeDate` (words `yesterday`, `today`, `tomorrow`, `asap`, `immediately`, `immediate`, `now`, casefold), `dates.AmbiguousDate`, or plain `ValueError`. Both subclass `ValueError`. Formats: `YYYY-MM-DD`; `Mon D YYYY` (`Jan 30 2026`); `Month D, YYYY` (`January 27, 2026`); `D-Mon-YYYY` (`26-Jan-2026`); `NN/NN/YYYY` per Decision 7. Month names are English, case-insensitive, 3-letter or full.
  - In `normalize`, OCR runs first, then:
    - due date: `RelativeDate` → `due_date_unresolved` (field `due_date`); `AmbiguousDate` → `ambiguous_date`; other `ValueError` → `unparseable_value`. Invoice date: `AmbiguousDate` → `ambiguous_date` (field `invoice_date`); anything else unparseable → `unparseable_value`. Nothing is resolved with the system clock.
    - both dates parsed and due < invoice → `due_before_invoice_date` (warning, expected = invoice date, observed = due date).
    - `payment_terms` matching `^net\s*(\d+)$` (casefold) with both dates parsed and `due != invoice + N days` → `terms_inconsistent` (warning, expected = `invoice + N` ISO, observed = due ISO, evidence = terms field evidence).
    - **Currency:** symbols seen in any raw amount (`$` → USD, `€` → EUR, `£` → GBP). Explicit `currency_raw` (stripped, uppercased) wins; explicit code ≠ USD → `unsupported_currency` (review, observed = code) and `invoice.currency` = that code; any symbol implying a different currency than the explicit code → `currency_conflict` (review). No code: a non-`$` symbol → `invoice.currency` = its code + `unsupported_currency`; otherwise USD with the `rule:dataset_usd_assumption` event and the `currency_assumed_usd` finding (Decision 9). This replaces the Phase 1 rule.
    - **Urgency:** `\b(urgent|immediately|asap|wire transfer|penalt(y|ies)|final notice)\b` (casefold) found in `notes_raw`, `payment_terms_raw`, or the snippet of any `unparsed_line` issue → one `risk_signal_urgency` finding (info) citing the first match. It never changes any other rule.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dates.py
@pytest.mark.parametrize("raw,expected", [
    ("2026-01-15", date(2026, 1, 15)), ("Jan 30 2026", date(2026, 1, 30)),
    ("January 27, 2026", date(2026, 1, 27)), ("26-Jan-2026", date(2026, 1, 26)),
    ("01/28/2026", date(2026, 1, 28)), ("28/01/2026", date(2026, 1, 28)), ("03/03/2026", date(2026, 3, 3))])
def test_formats(raw, expected): assert parse_date(raw) == expected

def test_ambiguous():
    with pytest.raises(AmbiguousDate): parse_date("02/03/2026")

@pytest.mark.parametrize("raw", ["yesterday", "ASAP", "Immediately"])
def test_relative(raw):
    with pytest.raises(RelativeDate): parse_date(raw)

# tests/test_normalize.py (add)
def codes_of(fs): return {f.code for f in fs}

def test_1002_terms_inconsistent():
    inv, fs = norm("invoice_1002.txt")
    assert (inv.invoice_date, inv.due_date) == (date(2026, 1, 30), date(2026, 1, 30))
    assert FindingCode.terms_inconsistent in codes_of(fs)

def test_1003_unresolved_and_urgency():
    inv, fs = norm("invoice_1003.txt")
    assert inv.due_date is None
    assert {FindingCode.due_date_unresolved, FindingCode.risk_signal_urgency} <= codes_of(fs)

def test_1007_slash_dates():
    inv, _ = norm("invoice_1007.csv")
    assert (inv.invoice_date, inv.due_date) == (date(2026, 1, 28), date(2026, 2, 28))

def test_1012_ocr_date():
    inv, _ = norm("invoice_1012.txt")
    assert inv.invoice_date == date(2026, 1, 26)
    assert any(e.provenance == "rule:ocr_digit" and e.field == "invoice_date" for e in inv.normalization_events)

def test_1014_eur_not_converted():
    inv, fs = norm("invoice_1014.xml")
    assert inv.currency == "EUR" and FindingCode.unsupported_currency in codes_of(fs)

def test_1013_json_and_pdf_same_currency_assumption_only_on_pdf():
    j, jf = norm("invoice_1013.json"); p, pf = norm("invoice_1013.pdf")
    assert j.currency == p.currency == "USD"
    assert FindingCode.currency_assumed_usd not in codes_of(jf)
    assert FindingCode.currency_assumed_usd in codes_of(pf)

def test_csv_without_symbols_assumes_usd():
    inv, fs = norm("invoice_1006.csv")
    assert inv.currency == "USD" and FindingCode.currency_assumed_usd in codes_of(fs)

def test_currency_conflict():
    d = parse_lines("s", [("line:1", "Currency: USD"), ("line:2", "Total: €10.00")])
    _, fs = normalize(d, ITEMS)
    assert FindingCode.currency_conflict in codes_of(fs)
```

Also: a constructed due date `2026-01-01` with invoice date `2026-01-15` → `due_before_invoice_date`; a constructed `Due Date: 02/03/2026` → `ambiguous_date`, and validation then reports no `missing_due_date` (Decision 14).

- [ ] **Step 2: Run** `uv run pytest tests/test_dates.py tests/test_normalize.py -q` → FAIL.
- [ ] **Step 3: Implement.** Existing Phase 1 currency tests keep passing (1001 still gets exactly one `currency_assumed_usd`, citing the first `$` line).
- [ ] **Step 4: Run** the full suite → PASS; ruff clean.
- [ ] **Step 5: Commit** — `git commit -m "feat: date parsing, currency resolution, terms check and urgency signals"`

---

### Task 11: Duplicates across formats and revisions (P2-10)

**Files:**
- Modify: `src/invoice_processing/ledger.py`, `src/invoice_processing/transitions.py`, `src/invoice_processing/agents/state.py`, `src/invoice_processing/agents/ingestion.py`, `src/invoice_processing/service.py`, `src/invoice_processing/payments.py`, `docs/tickets/P2-10-duplicates-formats-and-revisions.md` (replace "Known Phase 1 behaviour" with the new behaviour)
- Test: `tests/test_ledger.py`, `tests/test_service.py`, `tests/test_payments.py`, `tests/test_transitions.py`

**Interfaces:**
- Consumes: `semantic_hash` (unchanged definition: identity keys, currency, due date, canonical item/qty/unit-price lines, final total — it already excludes subtotal, tax lines, notes, terms, filename and layout), the `review` codes from Task 1.
- Produces:
  - `transitions.RUN_TRANSITIONS[extracted]` gains `duplicate`.
  - `ledger.IdentityCheck` — frozen dataclass `kind: Literal["new", "duplicate", "revision_after_payment", "version_conflict"]`, `prior: PriorOutcome | None`.
  - `ledger.check_identity(conn, invoice_id: str, version_id: str, run_id: str) -> IdentityCheck`, decided in this order:
    1. a payment exists for `invoice_id`: its version is this version → `duplicate` (prior = the paying run, with receipt); otherwise → `revision_after_payment` (prior = the paying run);
    2. the latest run on this `version_id`, other than `run_id`, with `retry_of IS NULL` and a status in `BUSINESS_OUTCOMES` → `duplicate` (prior = that run, receipt if any);
    3. any such run on another version of the same invoice → `version_conflict` (prior = the latest one);
    4. otherwise `new`.
    Failed and duplicate runs never count. Provisional `pending:` identities (missing vendor or number) are always `new`. If the current run has `retry_of` set, the check returns `new` (Decision 15).
  - Ingestion node, after `record_version` and `attach_run`:
    - `duplicate` → `update_run_status(extracted)` then `update_run_status(duplicate)`; state gets `status=duplicate`, `prior_run_id`, `receipt` (prior receipt or `None`); audit event `duplicate` with `prior_run_id`, `prior_status`, `match="semantic"`. The graph ends (`route_after` already maps unknown statuses to `end`).
    - `revision_after_payment` / `version_conflict` → append a finding with that code (severity review, `observed` = prior run id) to the recorded findings and continue normally; the gate's `R2_review` (or `R1_blocker`) decides.
  - `InvoiceState` gains `prior_run_id: str`.
  - `service.process_invoice`: `finish_run(..., prior_run_id=final.get("prior_run_id"))`; `_result` sets `prior_run_id` and keeps `receipt`; a `duplicate` run never changes `invoices.status` (already true).
  - `payments.pay`: an existing payment for the invoice whose `version` differs from the version being paid → `PaymentNotAuthorized("revision_after_payment")` instead of returning the old receipt. The same-version replay still returns the existing receipt with `created=False`.

- [ ] **Step 1: Write the failing tests** (`tests/test_service.py`; helper `run(name, db)` = `process_invoice(f"data/invoices/{name}", ExecutionMode.offline, db, date(2026, 1, 31))` on a seeded db; `payments(db)` counts rows):

```python
@pytest.mark.parametrize("first,second,first_status,second_status", [
    ("invoice_1011.txt", "invoice_1011.pdf", RunStatus.paid_mock, RunStatus.duplicate),
    ("invoice_1012.txt", "invoice_1012.pdf", RunStatus.paid_mock, RunStatus.duplicate),
    ("invoice_1013.json", "invoice_1013.pdf", RunStatus.rejected, RunStatus.duplicate)])
def test_alternate_format_is_duplicate(seeded_db, first, second, first_status, second_status):
    a = run(first, seeded_db); b = run(second, seeded_db)
    assert (a.status, b.status) == (first_status, second_status)
    assert b.prior_run_id == a.run_id and b.invoice_id == a.invoice_id
    assert b.receipt == a.receipt
    assert payments(seeded_db) == (1 if first_status is RunStatus.paid_mock else 0)

def test_revision_after_payment(seeded_db):
    a = run("invoice_1004.json", seeded_db); b = run("invoice_1004_revised.json", seeded_db)
    assert a.status is RunStatus.paid_mock and a.receipt.amount == Decimal("1890.00")
    assert b.status is RunStatus.needs_review and b.receipt is None
    assert FindingCode.revision_after_payment in {f.code for f in b.findings}
    assert payments(seeded_db) == 1

def test_revision_after_payment_reverse_order(seeded_db):
    a = run("invoice_1004_revised.json", seeded_db); b = run("invoice_1004.json", seeded_db)
    assert a.status is RunStatus.paid_mock and a.receipt.amount == Decimal("5940.00")
    assert b.status is RunStatus.needs_review
    assert FindingCode.revision_after_payment in {f.code for f in b.findings}

def test_version_conflict_when_prior_unpaid(seeded_db, tmp_path):
    # 1013 JSON is rejected; a changed copy of it under the same identity conflicts.
    a = run("invoice_1013.json", seeded_db)
    changed = tmp_path / "invoice_1013_changed.json"
    changed.write_text(Path("data/invoices/invoice_1013.json").read_text().replace('"quantity": 1,', '"quantity": 2,'))
    b = process_invoice(changed, ExecutionMode.offline, seeded_db, date(2026, 1, 31))
    assert a.status is RunStatus.rejected
    assert FindingCode.version_conflict in {f.code for f in b.findings}
    assert payments(seeded_db) == 0

def test_failed_prior_format_is_not_duplicate(seeded_db, monkeypatch):
    # First attempt fails inside validation; the PDF afterwards processes normally and pays.
    ...  # monkeypatch validation.run to raise once (pattern from test_failed_then_rerun_is_normal)
    assert run("invoice_1011.pdf", seeded_db).status is RunStatus.paid_mock
```

The existing `test_semantic_hash_ignores_filename_whitespace_and_line_order` covers the ticket's filename/whitespace criterion; add a test that 1011 TXT and 1011 PDF normalize to the same `semantic_hash`. Also add (carry-overs): `check_identity` unit tests for each kind; `find_prior_outcome` ignores runs with `retry_of`, returns the latest of several outcomes, and ignores `duplicate` runs; `mark_interrupted_runs` leaves terminal runs untouched; `payments.pay` raises `PaymentNotAuthorized("revision_after_payment")` when a payment exists for another version; `extracted → duplicate` is legal; a duplicate run leaves `invoices.status` and `invoices.current_version` unchanged.

- [ ] **Step 2: Run** `uv run pytest tests/test_service.py tests/test_ledger.py tests/test_payments.py tests/test_transitions.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full suite → PASS; ruff clean.
- [ ] **Step 5: Commit** — `git commit -m "feat: semantic duplicates across formats and revision conflicts"`

---

### Task 12: Fixture acceptance suite and Phase 2 close-out (P2-11)

**Files:**
- Create: `tests/test_acceptance.py`
- Modify: `tests/test_e2e.py`, `tests/test_policy.py`, `docs/PRD.md`, `docs/tickets/README.md`, `docs/tickets/P2-*.md` (status lines), `docs/tickets/P2-11-fixture-acceptance-suite.md` (record Decision 1 under "Decision needed")
- Test: `tests/test_acceptance.py`

**Interfaces:**
- Consumes: everything above; `service.process_invoice`.

- [ ] **Step 1: Write the acceptance suite.** One case per file, each on a fresh seeded database in `tmp_path`, offline, `evaluation_date=date(2026, 1, 31)`, network guard active, `payments.mock_payment` wrapped to count calls. For each case assert: the status; the paid amount when `paid_mock`; `mock_payment` called exactly once for `paid_mock` and never otherwise; the **set of blocker and review codes equals** `gating`; every code in `also` is present (info/warning).

```python
CASES = {
    "invoice_1001.txt": ("paid_mock", "5000.00", set(), {"currency_assumed_usd"}),
    "invoice_1002.txt": ("rejected", None, {"quantity_exceeds_stock"}, {"terms_inconsistent"}),
    "invoice_1003.txt": ("rejected", None, {"zero_stock", "due_date_unresolved"}, {"risk_signal_urgency"}),
    "invoice_1004.json": ("paid_mock", "1890.00", set(), set()),
    "invoice_1004_revised.json": ("paid_mock", "5940.00", set(), set()),
    "invoice_1005.json": ("rejected", None, {"quantity_exceeds_stock"}, set()),
    "invoice_1006.csv": ("paid_mock", "2750.00", set(), {"currency_assumed_usd"}),
    "invoice_1007.csv": ("rejected", None, {"quantity_exceeds_stock"}, set()),
    "invoice_1008.txt": ("rejected", None, {"unknown_item"}, set()),
    "invoice_1009.json": ("rejected", None, {"missing_vendor", "missing_due_date", "non_positive_quantity",
                                             "non_positive_total", "subtotal_mismatch"}, set()),
    "invoice_1010.txt": ("paid_mock", "7185.00", set(), set()),
    "invoice_1011.txt": ("paid_mock", "3000.00", set(), set()),
    "invoice_1011.pdf": ("paid_mock", "3000.00", set(), {"currency_assumed_usd"}),
    "invoice_1012.txt": ("paid_mock", "9975.00", set(), set()),
    "invoice_1012.pdf": ("paid_mock", "9975.00", set(), set()),
    "invoice_1013.json": ("rejected", None, {"quantity_exceeds_stock", "total_mismatch"}, set()),
    "invoice_1013.pdf": ("rejected", None, {"quantity_exceeds_stock", "total_mismatch"}, {"currency_assumed_usd"}),
    "invoice_1014.xml": ("needs_review", None, {"unsupported_currency", "non_usd_currency"}, set()),
    "invoice_1015.csv": ("paid_mock", "6500.00", set(), {"currency_assumed_usd"}),
    "invoice_1016.json": ("rejected", None, {"unknown_item"}, set()),
}
```

Additional per-case assertions (as separate tests, named after the fixture):
- 1002: label-alias events for `vendor`, `invoice_number`, `invoice_date`, `due_date`, `total`, `payment_terms`; `quantity_exceeds_stock` item `GadgetX`, expected `5`, observed `20`.
- 1003: `zero_stock` item `FakeItem`; `invoice.due_date is None` in the recorded version payload.
- 1005: `quantity_exceeds_stock` item `GadgetX` 8 > 5. 1007: items `WidgetA` (20 > 15) and `WidgetB` (15 > 10).
- 1008: `unknown_item` for exactly `SuperGizmo` and `MegaSprocket`.
- 1010: a `rule:item_qualifier` event; aggregated WidgetA quantity 12.
- 1012 (both): `rule:item_spacing`, `rule:ocr_digit`, `rule:invoice_number_format` events.
- 1013 (both): `quantity_exceeds_stock` for WidgetA 22, WidgetB 18, GadgetX 9; `total_mismatch` expected `22512.80`, observed `22562.80`.
- 1014: recorded currency `EUR`, no payment row.
- 1016: `unknown_item` for exactly `WidgetC`.
- Coverage: `sorted(p.name for p in Path("data/invoices").iterdir() if p.is_file()) == sorted(CASES)` (fails when a file is added without a case).
- Timing: the whole module runs in under 60 seconds (`pytest --durations` check by eye; no assertion).

If a fixture's actual output differs from this table, do not edit the table to match: find the cause, fix the parser or rule in the owning module, and report it. A table change needs a stated reason in the report.

- [ ] **Step 2: Carry-overs** — in `tests/test_e2e.py`, the repo-db test also compares the repo `inventory.db`'s SHA-256 (or its absence) before and after, not only mtime; e2e setup runs assert their first-run status. In `tests/test_policy.py`, add a `stated.total is None` case (no high-value rule; still `approved` when clean) and a combined high-value + disagreement case (`rule_ids == ["R3_high_value", "R3_model_disagreement"]`, `awaiting_human_approval`).
- [ ] **Step 3: Run** `uv run pytest tests/test_acceptance.py -q --durations=5` → PASS, then the full suite from a clean clone: `git clone . /tmp/<scratch>/p2 && cd …/p2 && uv sync && uv run pytest -q` → PASS (use the session scratchpad, not `/tmp`).
- [ ] **Step 4: Docs** — tick the four Phase 2 exit boxes in `docs/PRD.md`, each with the passing test ids (pattern from Phase 1); mark P2-01 … P2-11 `done` in their status lines and in `docs/tickets/README.md`; strike the P2-* and "Phase 2 deps" rows in the carry-overs table (move any item not done to its next ticket with a reason); add a "Run every sample" snippet to `docs/development.md` (`for f in data/invoices/*; do python main.py --invoice_path="$f" --db=/tmp/demo.db; done` with the note that a fresh db is needed for the per-file outcomes).
- [ ] **Step 5: Commit** — `git commit -m "test: fixture acceptance suite for all 20 invoices; close Phase 2"`
