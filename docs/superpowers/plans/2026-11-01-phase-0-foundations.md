# Phase 0 — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A scaffolded Python package with exact-money primitives, the shared Pydantic contracts, the SQLite schema and idempotent inventory seed, and pure validation functions (required fields, arithmetic, aggregation, inventory) proven against the supplied fixture values.

**Architecture:** `src/invoice_processing/` is a plain installed package; every Phase 0 module is pure or SQLite-only, with no agents, parsers, or network. Validation functions take a `NormalizedInvoice` and return `list[ValidationFinding]`; storage exposes a connection, an idempotent `init_schema`, a write-transaction helper, and read-only stock lookup. Nothing here is file-format aware; Phase 1 and 2 build parsers on top.

**Tech Stack:** Python 3.12, uv (lock/sync), hatchling, Pydantic v2, `sqlite3`, `decimal`, pytest, ruff.

**Spec:** `docs/tickets/P0-01-project-scaffolding.md` through `docs/tickets/P0-08-aggregation-and-inventory-check.md`, with `docs/PRD.md` §5 (business rules) and `docs/systemsdesign.md` (contracts, tables).

## Global Constraints

- `requires-python = ">=3.12"`; verified interpreter is Python 3.12.14 via `uv`.
- Money is `decimal.Decimal` only. `float` input is rejected everywhere. JSON serializes money as strings (e.g. `"22512.80"`).
- Rounding is `ROUND_HALF_UP` to the currency's minor unit; supported currencies are exactly `USD` and `EUR` (2 minor digits).
- A discrepancy greater than `0.01` blocks payment; `0.01` or less is tolerated and recorded.
- All SQL is parameterized; item names are never interpolated.
- Tests use temporary databases only; nothing touches `inventory.db` in the repo root.
- Seed records are exactly `WidgetA=15, WidgetB=10, GadgetX=5, FakeItem=0`; seeding never overwrites an existing stock value.
- Finding codes are stable identifiers from one enum; tests assert codes and severities, never message text.
- Evaluation date is always passed in; no function reads the system clock.
- Ruff rule set: `E, F, I, UP, B`, line length 100.

## Review Focus

1. Item names that differ from inventory only by case or whitespace (`widgeta`, `Widget A`) must be reported `unknown_item`, not silently matched; Phase 2 owns alias rules. Test in Task 10.
2. A quantity written with a fractional zero (`Decimal("10.0")`) is a whole number and must not raise `non_integer_quantity`. Test in Task 8.
3. A stated total of `-0.00` or `0` must raise `non_positive_total`. Test in Task 8.
4. `parse_decimal("$5,000.00")` must raise, not return `0` or `5`; messy text parsing belongs to Phase 2. Test in Task 2.
5. `init_schema` on a database where only some tables exist (crash mid-init, or a Phase 0 DB opened by a later version) must create the missing tables and never drop data. Test in Task 5.

---

### Task 1: Project scaffolding and tooling (P0-01)

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/invoice_processing/__init__.py`, `src/invoice_processing/py.typed`, `tests/__init__.py`, `tests/test_smoke.py`, `docs/development.md`
- Generated: `uv.lock`, `requirements.lock`

**Interfaces:**
- Produces: an installable package `invoice_processing` (editable via `uv sync`), `pytest` and `ruff` configured; `__version__ = "0.1.0"` in `__init__.py`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "invoice-processing"
version = "0.1.0"
description = "Galatiq case: multi-agent invoice processing prototype"
requires-python = ">=3.12"
dependencies = ["pydantic>=2.9"]

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/invoice_processing"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Write `.gitignore`**

Entries, one per line: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `*.db`, `*.db-journal`, `*.db-wal`, `*.db-shm`, `uploads/`, `output/`, `*.jsonl`, `.env`, `node_modules/`, `dist/`, `.DS_Store`.

- [ ] **Step 3: Write the package skeleton and smoke test**

`src/invoice_processing/__init__.py` contains `__version__ = "0.1.0"`. `src/invoice_processing/py.typed` is empty. `tests/__init__.py` is empty.

```python
# tests/test_smoke.py
import invoice_processing


def test_package_importable():
    assert invoice_processing.__version__ == "0.1.0"
```

- [ ] **Step 4: Create the lock and install**

Run: `uv python pin 3.12 && uv lock && uv sync && uv export --format requirements-txt --no-hashes > requirements.lock`
Expected: `uv.lock` and `requirements.lock` exist; `.python-version` contains `3.12`.

- [ ] **Step 5: Run tests and lint**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: `1 passed`; ruff reports no issues (run `uv run ruff format .` first if needed).

- [ ] **Step 6: Write `docs/development.md`**

Sections: Prerequisites (Python 3.12 via uv, Node 22 reserved for Phase 5); Setup (`uv sync`); Run tests (`uv run pytest`); Lint/format (`uv run ruff check .`, `uv run ruff format .`); Regenerate lock (`uv lock && uv export --format requirements-txt --no-hashes > requirements.lock`); pip-only install (`python3.12 -m venv .venv && .venv/bin/pip install -r requirements.lock -e .`); Verified on (Python 3.12.14, uv 0.12.5, macOS 25.6 — update when re-verified).

- [ ] **Step 7: Verify a stray database file is ignored**

Run: `touch inventory.db && git status --short && rm inventory.db`
Expected: `inventory.db` does not appear in the status output.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore .python-version uv.lock requirements.lock src tests docs/development.md
git commit -m "build: scaffold invoice_processing package with uv, pytest, ruff"
```

---

### Task 2: Money and currency primitives (P0-02)

**Files:**
- Create: `src/invoice_processing/money.py`
- Test: `tests/test_money.py`

**Interfaces:**
- Produces:
  - `MINOR_UNITS: dict[str, int] = {"USD": 2, "EUR": 2}`
  - `ONE_CENT: Decimal = Decimal("0.01")`
  - `class UnsupportedCurrencyError(ValueError)`
  - `parse_decimal(value: str | int | Decimal) -> Decimal` — raises `TypeError` for `float`/`bool`, `ValueError` for non-numeric strings.
  - `quantize(amount: Decimal, currency: str) -> Decimal` — `ROUND_HALF_UP` to `MINOR_UNITS[currency]`; raises `UnsupportedCurrencyError`.
  - `@dataclass(frozen=True) class MoneyDifference: difference: Decimal; within_tolerance: bool`
  - `compare(stated: Decimal, computed: Decimal, currency: str) -> MoneyDifference` — `difference = quantize(stated - computed)`; `within_tolerance = abs(difference) <= ONE_CENT`.
  - `format_money(amount: Decimal, currency: str) -> str` — `"USD 5,000.00"`.
  - `DecimalStr` — `Annotated[Decimal, BeforeValidator(_reject_float), PlainSerializer(str, return_type=str, when_used="json")]` for use in Pydantic models.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_money.py
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


@pytest.mark.parametrize("bad", ["$5,000.00", "abc", "", "1,000"])
def test_parse_decimal_rejects_messy_text(bad):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_money.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'invoice_processing.money'`.

- [ ] **Step 3: Implement `money.py`**

`parse_decimal`: reject `bool` before `int` (bool is an int subclass); for `str`, strip whitespace and construct `Decimal`, converting `InvalidOperation` to `ValueError`; reject empty string. `format_money`: `f"{currency} {quantize(amount, currency):,}"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_money.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/invoice_processing/money.py tests/test_money.py
git commit -m "feat: add exact decimal money primitives"
```

---

### Task 3: Enums and finding codes (P0-03, part 1)

**Files:**
- Create: `src/invoice_processing/codes.py`
- Test: `tests/test_codes.py`

**Interfaces:**
- Produces (all `enum.StrEnum`):
  - `Severity`: `info`, `warning`, `review`, `blocker` — `review` marks a finding that routes to `needs_review` (unsupported currency, ambiguous normalization, version conflict); `blocker` routes to `rejected`. No Phase 0 code uses `review` yet; Phase 2 adds those codes.
  - `RunStatus`: `received`, `extracted`, `validated`, `approval_pending`, `approved`, `awaiting_human_approval`, `paid_mock`, `rejected`, `needs_review`, `failed`, `duplicate`
  - `InvoiceStatus`: `processing`, `paid_mock`, `rejected`, `needs_review`, `awaiting_human_approval`, `failed`, `superseded`
  - `ExecutionMode`: `offline`, `live`
  - `SourceFormat`: `txt`, `json`, `csv`, `xml`, `pdf`
  - `FindingCode` with members: `missing_vendor`, `missing_invoice_number`, `missing_due_date`, `missing_currency`, `missing_total`, `missing_line_items`, `incomplete_line_item`, `non_positive_quantity`, `non_integer_quantity`, `non_positive_total`, `negative_unit_price`, `negative_tax`, `negative_shipping`, `due_date_past`, `line_total_mismatch`, `subtotal_mismatch`, `tax_mismatch`, `total_mismatch`, `rounding_tolerated`, `arithmetic_unverifiable`, `unknown_item`, `zero_stock`, `quantity_exceeds_stock`
  - `FINDING_DESCRIPTIONS: dict[FindingCode, str]` — one line per code.
  - `DEFAULT_SEVERITY: dict[FindingCode, Severity]` — blockers: all `missing_*`, `incomplete_line_item`, `non_*`, `negative_*`, `*_mismatch`, `unknown_item`, `zero_stock`, `quantity_exceeds_stock`; warnings: `due_date_past`, `arithmetic_unverifiable`; info: `rounding_tolerated`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_codes.py
from invoice_processing.codes import (
    DEFAULT_SEVERITY,
    FINDING_DESCRIPTIONS,
    FindingCode,
    InvoiceStatus,
    RunStatus,
    Severity,
)


def test_every_code_has_description_and_severity():
    for code in FindingCode:
        assert FINDING_DESCRIPTIONS[code].strip()
        assert DEFAULT_SEVERITY[code] in Severity


def test_duplicate_is_run_only_and_superseded_is_invoice_only():
    assert "duplicate" in RunStatus.__members__
    assert "duplicate" not in InvoiceStatus.__members__
    assert "superseded" in InvoiceStatus.__members__
    assert "superseded" not in RunStatus.__members__


def test_codes_are_strings():
    assert FindingCode.total_mismatch == "total_mismatch"
    assert str(Severity.blocker) == "blocker"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_codes.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `codes.py`** with the members listed in Interfaces.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_codes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/invoice_processing/codes.py tests/test_codes.py
git commit -m "feat: add status enums and finding codes"
```

---

### Task 4: Core data contracts (P0-03, part 2)

**Files:**
- Create: `src/invoice_processing/schemas.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Consumes: `DecimalStr` (Task 2); enums (Task 3).
- Produces (Pydantic `BaseModel`s, `model_config = ConfigDict(extra="forbid")`; every optional field defaults to `None`, every list to `[]`):
  - `EvidenceRef(source_id: str, location: str, snippet: str | None)` — `location` is a string such as `"line:9"`, `"row:3"`, `"page:1,line:4"`, `"$.line_items[2].quantity"`.
  - `SourceDocument(source_id: str, content_hash: str, original_name: str, format: SourceFormat, size_bytes: int, page_count: int | None, extracted_text: str | None, parser_version: str)`
  - `ExtractionIssue(code: str, message: str, evidence: list[EvidenceRef])`
  - `DraftLine(raw_name: str | None, quantity_raw: str | None, unit_price_raw: str | None, line_total_raw: str | None, note: str | None, evidence: list[EvidenceRef])`
  - `InvoiceDraft(source_id: str, vendor_raw, invoice_number_raw, revision_raw, invoice_date_raw, due_date_raw, currency_raw, subtotal_raw, tax_rate_raw, tax_raw, shipping_raw, total_raw: str | None, lines: list[DraftLine], issues: list[ExtractionIssue], evidence: list[EvidenceRef])`
  - `NormalizationEvent(field: str, raw_value: str | None, normalized_value: str | None, evidence: list[EvidenceRef], provenance: str)` — provenance is `"rule:<name>"` or `"model:<provider>/<model>"`.
  - `LineItem(item: str | None, quantity: DecimalStr | None, unit_price: DecimalStr | None, line_total: DecimalStr | None, note: str | None, evidence: list[EvidenceRef])`
  - `StatedTotals(subtotal, tax_rate, tax, shipping, total: DecimalStr | None)`
  - `ComputedTotals(line_totals: list[DecimalStr | None], subtotal: DecimalStr | None, tax: DecimalStr | None, shipping: DecimalStr | None, total: DecimalStr | None)`
  - `NormalizedInvoice(source_id: str, vendor_name: str | None, vendor_key: str | None, invoice_number: str | None, invoice_number_key: str | None, revision: str | None, invoice_date: date | None, due_date: date | None, currency: str | None, lines: list[LineItem], stated: StatedTotals, computed: ComputedTotals | None, normalization_events: list[NormalizationEvent])`
  - `ValidationFinding(code: FindingCode, severity: Severity, field: str | None, item: str | None, expected: str | None, observed: str | None, evidence: list[EvidenceRef], resolved: bool = False)`
  - `ApprovalDecision(initial_recommendation: str, critique_summary: str | None, revised_recommendation: str | None, final_decision: str, reasons: list[str], policy_version: str, mode: ExecutionMode, provider: str | None, model: str | None)`
  - `MockReceipt(receipt_id: str, amount: DecimalStr, currency: str, paid_at: datetime)`
  - `ProcessingResult(run_id: str, invoice_id: str | None, status: RunStatus, mode: ExecutionMode, findings: list[ValidationFinding], decision: ApprovalDecision | None, receipt: MockReceipt | None, timings_ms: dict[str, int], errors: list[str])`
  - `AggregatedItem(item: str, quantity: DecimalStr, line_indexes: list[int])`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_schemas.py
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoice_processing import schemas
from invoice_processing.codes import FindingCode, Severity

CONTRACTS = [
    schemas.EvidenceRef, schemas.SourceDocument, schemas.InvoiceDraft, schemas.NormalizationEvent,
    schemas.NormalizedInvoice, schemas.ValidationFinding, schemas.ApprovalDecision,
    schemas.ProcessingResult, schemas.AggregatedItem,
]


def inv_1009_draft() -> schemas.InvoiceDraft:
    return schemas.InvoiceDraft(
        source_id="src-1009",
        vendor_raw="",
        invoice_number_raw="INV-1009",
        invoice_date_raw="2026-01-15",
        due_date_raw=None,
        currency_raw="USD",
        subtotal_raw="1000.00",
        tax_rate_raw="0.0",
        tax_raw="0.00",
        total_raw="-250.00",
        lines=[
            schemas.DraftLine(raw_name="WidgetA", quantity_raw="-5", unit_price_raw="250.00"),
            schemas.DraftLine(raw_name="WidgetB", quantity_raw="2", unit_price_raw="500.00"),
        ],
    )


def test_draft_holds_invalid_data_without_raising():
    draft = inv_1009_draft()
    assert draft.lines[0].quantity_raw == "-5"
    assert draft.total_raw == "-250.00"


@pytest.mark.parametrize("model", CONTRACTS)
def test_json_schema_generates(model):
    assert model.model_json_schema()["title"] == model.__name__


def test_normalized_invoice_round_trip_keeps_decimal_strings():
    inv = schemas.NormalizedInvoice(
        source_id="s",
        currency="USD",
        due_date=date(2026, 2, 1),
        lines=[schemas.LineItem(item="WidgetA", quantity=Decimal("10"), unit_price=Decimal("250.00"))],
        stated=schemas.StatedTotals(total=Decimal("22512.80")),
    )
    dumped = inv.model_dump_json()
    assert '"total":"22512.80"' in dumped
    assert schemas.NormalizedInvoice.model_validate_json(dumped) == inv


def test_finding_round_trip():
    f = schemas.ValidationFinding(
        code=FindingCode.total_mismatch, severity=Severity.blocker,
        field="total", expected="22512.80", observed="22562.80",
    )
    assert schemas.ValidationFinding.model_validate_json(f.model_dump_json()) == f


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        schemas.EvidenceRef(source_id="s", location="line:1", bogus=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `schemas.py`** with the models in Interfaces. Use `from __future__ import annotations` sparingly; Pydantic needs real types for `date`/`datetime`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/invoice_processing/schemas.py tests/test_schemas.py
git commit -m "feat: add core Pydantic contracts"
```

---

### Task 5: SQLite schema and storage module (P0-04)

**Files:**
- Create: `src/invoice_processing/storage.py`, `tests/conftest.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces:
  - `SCHEMA_VERSION: int = 1`
  - `class SchemaVersionError(RuntimeError)`
  - `connect(path: str | Path) -> sqlite3.Connection` — `isolation_level=None` (manual transactions), `row_factory = sqlite3.Row`, `PRAGMA foreign_keys = ON`, `PRAGMA journal_mode = WAL`.
  - `init_schema(conn) -> None` — `CREATE TABLE IF NOT EXISTS` for every table below; sets `PRAGMA user_version = 1` when it is `0`; raises `SchemaVersionError` when `user_version > SCHEMA_VERSION`.
  - `write_transaction(conn)` — `contextlib.contextmanager`: `BEGIN IMMEDIATE`, yield, `COMMIT`; on exception `ROLLBACK` and re-raise.
  - `get_stock(conn, items: Iterable[str]) -> dict[str, int | None]` — one parameterized query; unknown items map to `None`; empty input returns `{}`.
  - `tests/conftest.py` fixtures: `db_path(tmp_path) -> Path`, `conn(db_path)` (connected with schema, closed on teardown).

The schema (money as `TEXT` decimal strings, timestamps as ISO-8601 UTC `TEXT`):

```sql
CREATE TABLE IF NOT EXISTS inventory (
  item TEXT PRIMARY KEY,
  stock INTEGER NOT NULL CHECK (stock >= 0));
CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL UNIQUE, original_name TEXT NOT NULL,
  format TEXT NOT NULL, size_bytes INTEGER NOT NULL, parser_version TEXT, extracted_text TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invoices (
  invoice_id TEXT PRIMARY KEY, vendor_key TEXT NOT NULL, invoice_number_key TEXT NOT NULL,
  current_version INTEGER, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (vendor_key, invoice_number_key));
CREATE TABLE IF NOT EXISTS invoice_versions (
  version_id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
  version INTEGER NOT NULL, parent_version INTEGER, origin TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(source_id), semantic_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE (invoice_id, version));
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id),
  invoice_id TEXT REFERENCES invoices(invoice_id), version_id TEXT REFERENCES invoice_versions(version_id),
  mode TEXT NOT NULL, status TEXT NOT NULL, stage TEXT, error_code TEXT, error_message TEXT,
  retry_of TEXT REFERENCES runs(run_id), evaluation_date TEXT, started_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS findings (
  finding_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(run_id),
  version_id TEXT REFERENCES invoice_versions(version_id), code TEXT NOT NULL, severity TEXT NOT NULL,
  payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
  decision_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
  version_id TEXT REFERENCES invoice_versions(version_id), payload_json TEXT NOT NULL,
  policy_version TEXT NOT NULL, mode TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS corrections (
  correction_id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
  from_version INTEGER NOT NULL, to_version INTEGER NOT NULL, field TEXT NOT NULL, old_value TEXT,
  new_value TEXT NOT NULL, evidence_location TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS human_reviews (
  review_id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
  version INTEGER NOT NULL, action TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL,
  policy_version TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments (
  payment_id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL UNIQUE REFERENCES invoices(invoice_id),
  version INTEGER NOT NULL, run_id TEXT NOT NULL REFERENCES runs(run_id), amount TEXT NOT NULL,
  currency TEXT NOT NULL, receipt_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT REFERENCES runs(run_id),
  invoice_id TEXT REFERENCES invoices(invoice_id), version_id TEXT, stage TEXT NOT NULL,
  event TEXT NOT NULL, actor TEXT, payload_json TEXT, created_at TEXT NOT NULL);
```

- [ ] **Step 1: Write `tests/conftest.py` and the failing tests**

```python
# tests/conftest.py
from pathlib import Path

import pytest

from invoice_processing import storage


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    c = storage.connect(db_path)
    storage.init_schema(c)
    yield c
    c.close()
```

```python
# tests/test_storage.py
import sqlite3

import pytest

from invoice_processing import storage

TABLES = {
    "inventory", "sources", "invoices", "invoice_versions", "runs", "findings",
    "decisions", "corrections", "human_reviews", "payments", "audit_events",
}


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows} - {"sqlite_sequence"}


def test_init_schema_creates_all_tables_and_is_idempotent(conn):
    assert table_names(conn) == TABLES
    assert conn.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
    before = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    storage.init_schema(conn)
    assert conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == before


def test_init_schema_fills_in_missing_tables_without_dropping_data(db_path):
    c = storage.connect(db_path)
    c.execute("CREATE TABLE inventory (item TEXT PRIMARY KEY, stock INTEGER NOT NULL CHECK (stock >= 0))")
    c.execute("INSERT INTO inventory VALUES ('WidgetA', 15)")
    storage.init_schema(c)
    assert table_names(c) == TABLES
    assert c.execute("SELECT stock FROM inventory WHERE item='WidgetA'").fetchone()[0] == 15


def test_future_schema_version_is_refused(db_path):
    c = storage.connect(db_path)
    c.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION + 1}")
    with pytest.raises(storage.SchemaVersionError):
        storage.init_schema(c)


def test_connection_settings(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def _minimal_invoice_rows(conn):
    now = "2026-01-31T00:00:00Z"
    conn.execute(
        "INSERT INTO sources VALUES ('s1','h1','a.txt','txt',10,NULL,NULL,?)", (now,)
    )
    conn.execute(
        "INSERT INTO invoices VALUES ('i1','widgets inc.','1001',1,'processing',?,?)", (now, now)
    )
    conn.execute(
        "INSERT INTO runs (run_id, source_id, invoice_id, mode, status, started_at)"
        " VALUES ('r1','s1','i1','offline','received',?)",
        (now,),
    )


def test_one_payment_per_invoice_identity(conn):
    _minimal_invoice_rows(conn)
    row = ("p1", "i1", 1, "r1", "5000.00", "USD", "rcpt-1", "success", "2026-01-31T00:00:00Z")
    conn.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?)", row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?)", ("p2", *row[1:6], "rcpt-2", *row[7:]))


def test_write_transaction_rolls_back_on_error(conn):
    with pytest.raises(RuntimeError):
        with storage.write_transaction(conn):
            conn.execute("INSERT INTO inventory VALUES ('X', 1)")
            raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0


def test_get_stock(conn):
    conn.execute("INSERT INTO inventory VALUES ('WidgetA', 15), ('FakeItem', 0)")
    assert storage.get_stock(conn, ["WidgetA", "FakeItem", "Nope"]) == {
        "WidgetA": 15, "FakeItem": 0, "Nope": None,
    }
    assert storage.get_stock(conn, []) == {}


def test_get_stock_is_parameterized(conn):
    conn.execute("INSERT INTO inventory VALUES ('WidgetA', 15)")
    assert storage.get_stock(conn, ["WidgetA' OR '1'='1"]) == {"WidgetA' OR '1'='1": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError` (from conftest import).

- [ ] **Step 3: Implement `storage.py`** per Interfaces. Keep the DDL as one module-level tuple of statements executed in order.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/invoice_processing/storage.py tests/conftest.py tests/test_storage.py
git commit -m "feat: add SQLite schema, transactions, and stock lookup"
```

---

### Task 6: Idempotent inventory seed (P0-05)

**Files:**
- Create: `src/invoice_processing/seed.py`
- Modify: `docs/development.md` (add "Seed the inventory" section)
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: `storage.connect`, `storage.init_schema`, `storage.write_transaction`.
- Produces:
  - `SEED_ITEMS: dict[str, int] = {"WidgetA": 15, "WidgetB": 10, "GadgetX": 5, "FakeItem": 0}`
  - `@dataclass class SeedReport: inserted: list[str]; unchanged: list[str]; differing: list[tuple[str, int, int]]` — `(item, existing_stock, seed_stock)`.
  - `seed_inventory(conn) -> SeedReport` — one write transaction; inserts missing rows only.
  - `main(argv: list[str] | None = None) -> int` — argparse with `--db PATH` (default `inventory.db`) and `--fresh`; prints `Inserted: …`, `Unchanged: …`, and `WARNING: <item> stock <existing> differs from seed <seed>` lines; `--fresh` on an existing path prints `error: <path> already exists` to **stderr** and returns `2` without touching the file; otherwise returns `0`. Report lines go to stdout.
  - `if __name__ == "__main__": raise SystemExit(main())` so `uv run python -m invoice_processing.seed --db PATH` works.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_seed.py
from invoice_processing import seed, storage


def test_seed_twice_reports_unchanged(conn):
    first = seed.seed_inventory(conn)
    assert sorted(first.inserted) == ["FakeItem", "GadgetX", "WidgetA", "WidgetB"]
    second = seed.seed_inventory(conn)
    assert second.inserted == [] and sorted(second.unchanged) == sorted(seed.SEED_ITEMS)
    assert storage.get_stock(conn, seed.SEED_ITEMS) == seed.SEED_ITEMS


def test_seed_keeps_existing_values_and_reports_difference(conn):
    seed.seed_inventory(conn)
    conn.execute("UPDATE inventory SET stock = 99 WHERE item = 'WidgetA'")
    report = seed.seed_inventory(conn)
    assert report.differing == [("WidgetA", 99, 15)]
    assert storage.get_stock(conn, ["WidgetA"]) == {"WidgetA": 99}


def test_cli_creates_and_seeds(db_path, capsys):
    assert seed.main(["--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert "Inserted:" in out and "WidgetA" in out
    c = storage.connect(db_path)
    assert storage.get_stock(c, ["GadgetX"]) == {"GadgetX": 5}


def test_cli_fresh_refuses_existing_path(db_path, capsys):
    db_path.write_bytes(b"not a database")
    assert seed.main(["--db", str(db_path), "--fresh"]) == 2
    assert db_path.read_bytes() == b"not a database"
    assert "exists" in capsys.readouterr().err


def test_cli_warns_on_difference(db_path, capsys):
    seed.main(["--db", str(db_path)])
    c = storage.connect(db_path)
    c.execute("UPDATE inventory SET stock = 99 WHERE item = 'WidgetA'")
    c.close()
    seed.main(["--db", str(db_path)])
    assert "WARNING: WidgetA stock 99 differs from seed 15" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_seed.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `seed.py`** per Interfaces.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_seed.py -v`
Expected: PASS.

- [ ] **Step 5: Document the command**

Add to `docs/development.md`: `uv run python -m invoice_processing.seed --db inventory.db` and the `--fresh` behavior.

- [ ] **Step 6: Commit**

```bash
git add src/invoice_processing/seed.py tests/test_seed.py docs/development.md
git commit -m "feat: add idempotent inventory seed with CLI"
```

---

### Task 7: Validation test helpers

**Files:**
- Create: `tests/helpers.py`

**Interfaces:**
- Consumes: `schemas` (Task 4).
- Produces builders used by Tasks 8–10:
  - `line(item: str | None, qty: str | None, price: str | None, total: str | None = None) -> LineItem` (strings converted with `Decimal`, `None` passed through).
  - `invoice(*, lines: list[LineItem], vendor="Vendor", number="INV-1", currency="USD", due="2026-02-01", subtotal=None, tax_rate=None, tax=None, shipping=None, total=None) -> NormalizedInvoice` — any `None` (including `vendor=None`, `due=None`) is stored as `None`; strings become `date.fromisoformat` / `Decimal`; `vendor_key` is `vendor.strip().lower()` when vendor is a string.
  - `inv_1001()`: WidgetA 10 @ 250.00, WidgetB 5 @ 500.00; subtotal 5000.00, tax_rate 0, tax 0.00, total 5000.00.
  - `inv_1009()`: vendor `None`, due `None`, WidgetA −5 @ 250.00, WidgetB 2 @ 500.00; subtotal 1000.00, tax 0.00, total −250.00.
  - `inv_1013()`: the eight JSON lines (15/10/5/5/8/3/2/1 of WidgetA/WidgetB/GadgetX/WidgetA/WidgetB/GadgetX/WidgetA/GadgetX at 250/500/750/240/480/750/250/750, line totals 3750/5000/3750/1200/3840/2250/500/750); subtotal 21040.00, tax_rate 0.07, tax 1472.80, total 22562.80.
  - `inv_1010()`: WidgetA 8 @ 250, WidgetB 4 @ 500, GadgetX 2 @ 750, WidgetA 4 @ 300; subtotal 6700.00, tax 335.00, shipping 150.00, total 7185.00.
  - `codes(findings) -> list[FindingCode]`.

- [ ] **Step 1: Write `tests/helpers.py`** with the builders above (no test of its own; Task 8's tests exercise it).

- [ ] **Step 2: Lint**

Run: `uv run ruff check tests/helpers.py`
Expected: no issues.

- [ ] **Step 3: Commit**

```bash
git add tests/helpers.py
git commit -m "test: add NormalizedInvoice fixture builders"
```

---

### Task 8: Required-field and value-sign checks (P0-06)

**Files:**
- Create: `src/invoice_processing/validation.py`
- Test: `tests/test_validation_fields.py`

**Interfaces:**
- Consumes: `schemas.NormalizedInvoice`, `schemas.ValidationFinding`, `codes`.
- Produces (in `validation.py`):
  - `check_required_fields(invoice: NormalizedInvoice) -> list[ValidationFinding]` — empty/whitespace strings count as missing; `missing_line_items` when `lines == []`; `incomplete_line_item` per line lacking `item`, `quantity`, or `unit_price` (with `item` set to the index as `"line:<i>"` when the name is missing). Severity from `DEFAULT_SEVERITY`.
  - `check_value_signs(invoice) -> list[ValidationFinding]` — per line: `non_positive_quantity` (≤ 0), `non_integer_quantity` (`q != q.to_integral_value()`); `negative_unit_price`; invoice-level `non_positive_total` (stated total ≤ 0), `negative_tax`, `negative_shipping`. Fields that are `None` are skipped (required-fields owns missing).
  - `check_due_date(invoice, evaluation_date: date) -> list[ValidationFinding]` — `due_date_past` (warning) when `due_date < evaluation_date`; `observed` = due date ISO, `expected` = evaluation date ISO; nothing when `due_date is None`.
  - `_finding(code, *, field=None, item=None, expected=None, observed=None, evidence=()) -> ValidationFinding` — helper applying `DEFAULT_SEVERITY`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_validation_fields.py
from datetime import date
from decimal import Decimal

from invoice_processing import validation
from invoice_processing.codes import FindingCode as C, Severity
from tests.helpers import codes, inv_1001, inv_1009, invoice, line


def test_1001_has_no_blockers():
    inv = inv_1001()
    findings = validation.check_required_fields(inv) + validation.check_value_signs(inv)
    assert findings == []


def test_1009_required_and_sign_blockers():
    inv = inv_1009()
    got = set(codes(validation.check_required_fields(inv) + validation.check_value_signs(inv)))
    assert {C.missing_vendor, C.missing_due_date, C.non_positive_quantity, C.non_positive_total} <= got
    assert all(f.severity == Severity.blocker for f in validation.check_required_fields(inv))


def test_whitespace_vendor_is_missing():
    inv = invoice(lines=[line("WidgetA", "1", "1")], vendor="   ")
    assert C.missing_vendor in codes(validation.check_required_fields(inv))


def test_missing_and_incomplete_lines():
    assert C.missing_line_items in codes(validation.check_required_fields(invoice(lines=[])))
    inv = invoice(lines=[line("WidgetA", None, "250.00")])
    f = [x for x in validation.check_required_fields(inv) if x.code == C.incomplete_line_item]
    assert len(f) == 1 and f[0].item == "WidgetA"


def test_quantity_with_fractional_zero_is_integer():
    inv = invoice(lines=[line("WidgetA", "10.0", "250.00")])
    assert C.non_integer_quantity not in codes(validation.check_value_signs(inv))
    inv = invoice(lines=[line("WidgetA", "2.5", "250.00")])
    assert C.non_integer_quantity in codes(validation.check_value_signs(inv))


def test_zero_and_negative_zero_total():
    for total in ("0", "-0.00"):
        inv = invoice(lines=[line("WidgetA", "1", "1")], total=total)
        assert C.non_positive_total in codes(validation.check_value_signs(inv))


def test_negative_price_tax_shipping():
    inv = invoice(lines=[line("WidgetA", "1", "-1")], tax="-1", shipping="-2", total="1")
    got = codes(validation.check_value_signs(inv))
    assert {C.negative_unit_price, C.negative_tax, C.negative_shipping} <= set(got)


def test_due_date_past_is_warning_and_depends_only_on_evaluation_date():
    inv = inv_1001()  # due 2026-02-01
    assert validation.check_due_date(inv, date(2026, 1, 31)) == []
    f = validation.check_due_date(inv, date(2026, 2, 2))
    assert codes(f) == [C.due_date_past] and f[0].severity == Severity.warning
    assert f[0].observed == "2026-02-01" and f[0].expected == "2026-02-02"
    assert validation.check_due_date(invoice(lines=[], due=None), date(2026, 2, 2)) == []


def test_observed_values_are_strings():
    inv = invoice(lines=[line("WidgetA", "-5", "250.00")], total="1")
    f = [x for x in validation.check_value_signs(inv) if x.code == C.non_positive_quantity][0]
    assert f.observed == "-5" and f.item == "WidgetA" and isinstance(f.observed, str)
    assert Decimal(f.observed) == Decimal("-5")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_validation_fields.py -v`
Expected: FAIL with `ModuleNotFoundError: invoice_processing.validation`.

- [ ] **Step 3: Implement the three check functions and `_finding` in `validation.py`.**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_validation_fields.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/invoice_processing/validation.py tests/test_validation_fields.py
git commit -m "feat: add required-field, sign, and due-date checks"
```

---

### Task 9: Arithmetic reconciliation (P0-07)

**Files:**
- Modify: `src/invoice_processing/validation.py`
- Test: `tests/test_validation_arithmetic.py`

**Interfaces:**
- Consumes: `money.quantize`, `money.compare`, `schemas.ComputedTotals`.
- Produces: `reconcile_totals(invoice: NormalizedInvoice) -> tuple[ComputedTotals, list[ValidationFinding]]` with these rules (currency defaults to `USD` for quantization when `invoice.currency is None`):
  1. Per line: if `quantity` and `unit_price` present, `line_total = quantize(q × p)`; if a stated `line_total` exists, `compare` → `line_total_mismatch` (blocker) when outside tolerance, `rounding_tolerated` (info) when non-zero but within. A line missing `quantity` or `unit_price` yields `None` and one `arithmetic_unverifiable` (warning, `item` = line name or index).
  2. `computed.subtotal` = sum of non-`None` line totals, only when every line total is known; otherwise `None` and no subtotal/total comparison.
  3. `subtotal_mismatch` when `stated.subtotal` present and differs from `computed.subtotal` beyond tolerance.
  4. `computed.tax` = `stated.tax` if present, else `0`; `computed.shipping` likewise. When both `stated.tax_rate` and `stated.tax` are present: `tax_mismatch` if `quantize(computed.subtotal × tax_rate)` differs from `stated.tax` beyond tolerance.
  5. `computed.total = computed.subtotal + computed.tax + computed.shipping`; `total_mismatch` when `stated.total` present and differs beyond tolerance; `rounding_tolerated` when non-zero within tolerance. Findings carry `expected` = computed, `observed` = stated, both as plain decimal strings.
  6. Stated values are never modified; the returned `ComputedTotals` is separate.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_validation_arithmetic.py
from decimal import Decimal

from invoice_processing import validation
from invoice_processing.codes import FindingCode as C, Severity
from tests.helpers import codes, inv_1009, inv_1010, inv_1013, invoice, line


def test_1013_total_mismatch_of_50():
    computed, findings = validation.reconcile_totals(inv_1013())
    assert computed.subtotal == Decimal("21040.00")
    assert computed.tax == Decimal("1472.80")
    assert computed.total == Decimal("22512.80")
    [f] = [x for x in findings if x.code == C.total_mismatch]
    assert f.severity == Severity.blocker
    assert f.expected == "22512.80" and f.observed == "22562.80"
    assert C.subtotal_mismatch not in codes(findings)
    assert C.tax_mismatch not in codes(findings)


def test_1010_adds_up():
    computed, findings = validation.reconcile_totals(inv_1010())
    assert computed.total == Decimal("7185.00")
    assert findings == []


def test_1009_subtotal_mismatch():
    computed, findings = validation.reconcile_totals(inv_1009())
    assert computed.subtotal == Decimal("-250.00")
    assert C.subtotal_mismatch in codes(findings)


def test_one_cent_tolerated_two_cents_blocks():
    base = [line("WidgetA", "1", "100.00")]
    _, f = validation.reconcile_totals(invoice(lines=base, total="100.01"))
    assert codes(f) == [C.rounding_tolerated]
    _, f = validation.reconcile_totals(invoice(lines=base, total="100.02"))
    assert codes(f) == [C.total_mismatch]


def test_missing_tax_and_shipping_count_as_zero():
    _, f = validation.reconcile_totals(invoice(lines=[line("SuperGizmo", "12", "400.00"), line("MegaSprocket", "6", "850.00")], total="9900.00"))
    assert f == []


def test_unverifiable_line_skips_totals():
    computed, f = validation.reconcile_totals(invoice(lines=[line("WidgetA", None, "250.00")], total="250.00"))
    assert computed.subtotal is None and computed.total is None
    assert codes(f) == [C.arithmetic_unverifiable] and f[0].severity == Severity.warning


def test_line_total_mismatch():
    _, f = validation.reconcile_totals(invoice(lines=[line("WidgetA", "2", "250.00", total="600.00")]))
    assert C.line_total_mismatch in codes(f)


def test_tax_rate_mismatch():
    _, f = validation.reconcile_totals(invoice(lines=[line("WidgetA", "1", "100.00")], tax_rate="0.10", tax="5.00", total="105.00"))
    assert C.tax_mismatch in codes(f)


def test_stated_values_untouched():
    inv = inv_1013()
    validation.reconcile_totals(inv)
    assert inv.stated.total == Decimal("22562.80")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_validation_arithmetic.py -v`
Expected: FAIL with `AttributeError: … has no attribute 'reconcile_totals'`.

- [ ] **Step 3: Implement `reconcile_totals`** per the six rules.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_validation_arithmetic.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/invoice_processing/validation.py tests/test_validation_arithmetic.py
git commit -m "feat: add decimal arithmetic reconciliation"
```

---

### Task 10: Item aggregation and inventory comparison (P0-08)

**Files:**
- Modify: `src/invoice_processing/validation.py`
- Test: `tests/test_validation_inventory.py`

**Interfaces:**
- Consumes: `storage.get_stock`, `seed.seed_inventory`, `schemas.AggregatedItem`.
- Produces:
  - `aggregate_quantities(lines: list[LineItem]) -> dict[str, AggregatedItem]` — keyed by the exact `item` string (no case folding, no whitespace changes); lines with `item is None` or `quantity is None` are skipped; insertion order preserved.
  - `check_inventory(aggregated: dict[str, AggregatedItem], stock: dict[str, int | None]) -> list[ValidationFinding]` — per item: `unknown_item` when `stock.get(item) is None`; `zero_stock` when `0`; `quantity_exceeds_stock` when `quantity > stock` (`observed` = requested, `expected` = available, both strings). Exactly one finding per item.
  - `check_inventory_against_db(conn, aggregated) -> list[ValidationFinding]` — fetches stock with `get_stock` and delegates.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_validation_inventory.py
from decimal import Decimal

from invoice_processing import seed, storage, validation
from invoice_processing.codes import FindingCode as C
from tests.helpers import codes, inv_1001, inv_1013, invoice, line

SEED = dict(seed.SEED_ITEMS)


def test_1013_aggregates_and_exceeds():
    agg = validation.aggregate_quantities(inv_1013().lines)
    assert {k: v.quantity for k, v in agg.items()} == {
        "WidgetA": Decimal("22"), "WidgetB": Decimal("18"), "GadgetX": Decimal("9"),
    }
    assert agg["WidgetA"].line_indexes == [0, 3, 6]
    f = validation.check_inventory(agg, SEED)
    assert codes(f) == [C.quantity_exceeds_stock] * 3


def test_1002_gadgetx_exceeds():
    agg = validation.aggregate_quantities([line("GadgetX", "20", "750")])
    [f] = validation.check_inventory(agg, SEED)
    assert f.code == C.quantity_exceeds_stock and f.observed == "20" and f.expected == "5"


def test_zero_and_unknown():
    agg = validation.aggregate_quantities(
        [line("FakeItem", "100", "1000"), line("SuperGizmo", "12", "400"), line("WidgetC", "3", "350")]
    )
    f = {x.item: x.code for x in validation.check_inventory(agg, SEED)}
    assert f == {"FakeItem": C.zero_stock, "SuperGizmo": C.unknown_item, "WidgetC": C.unknown_item}


def test_1001_within_stock():
    assert validation.check_inventory(validation.aggregate_quantities(inv_1001().lines), SEED) == []


def test_case_and_whitespace_variants_are_unknown():
    agg = validation.aggregate_quantities([line("widgeta", "1", "1"), line("Widget A", "1", "1")])
    assert [x.code for x in validation.check_inventory(agg, SEED)] == [C.unknown_item, C.unknown_item]


def test_lines_without_item_or_quantity_are_skipped():
    agg = validation.aggregate_quantities([line(None, "1", "1"), line("WidgetA", None, "1")])
    assert agg == {}


def test_against_db_does_not_change_stock(conn):
    seed.seed_inventory(conn)
    f = validation.check_inventory_against_db(conn, validation.aggregate_quantities(inv_1013().lines))
    assert len(f) == 3
    assert storage.get_stock(conn, seed.SEED_ITEMS) == seed.SEED_ITEMS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_validation_inventory.py -v`
Expected: FAIL with `AttributeError: … 'aggregate_quantities'`.

- [ ] **Step 3: Implement the three functions** per Interfaces.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_validation_inventory.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/invoice_processing/validation.py tests/test_validation_inventory.py
git commit -m "feat: add quantity aggregation and inventory checks"
```

---

### Task 11: Phase 0 exit verification

**Files:**
- Modify: `docs/development.md`, `docs/tickets/README.md`, `docs/tickets/P0-0*.md` (status lines), `docs/PRD.md` (Phase 0 checkboxes)

- [ ] **Step 1: Full suite and lint**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: all tests PASS; ruff clean.

- [ ] **Step 2: Clean-clone check**

Run (from the scratchpad directory, not inside the repo): `git clone /Users/jorgealejandrodiez/Desktop/galatiq-case-invoices p0check && cd p0check && uv sync && uv run pytest && uv run python -m invoice_processing.seed --db check.db && uv run python -m invoice_processing.seed --db check.db`
Expected: tests pass; first seed prints four `Inserted`; second prints four `Unchanged`; delete `p0check` afterwards.

- [ ] **Step 3: Record versions and mark tickets done**

In `docs/development.md` "Verified on": Python 3.12.14, uv 0.12.5, macOS 25.6.0, date. In each `P0-0*.md` header change `Status: todo` → `Status: done`; in `docs/tickets/README.md` Phase 0 table set every row to `done`; tick the two Phase 0 exit-criteria boxes in `docs/PRD.md`.

- [ ] **Step 4: Commit**

```bash
git add docs/development.md docs/tickets docs/PRD.md
git commit -m "docs: mark Phase 0 complete"
```
