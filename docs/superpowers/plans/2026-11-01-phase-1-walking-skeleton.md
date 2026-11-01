# Phase 1 — Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** INV-1001 (TXT) flows through `python main.py --invoice_path=data/invoices/invoice_1001.txt` to a persisted USD 5,000.00 mock receipt in offline mode; rerunning never pays twice; offline mode makes no network calls.

**Architecture:** One processing service (`service.process_invoice`) intakes and hashes the file, opens a run, short-circuits exact duplicates, and otherwise invokes a LangGraph graph of four agent nodes (ingestion → validation → approval → payment/outcome). Agents are plain functions over a typed state plus an injected `Deps` bundle (connection, provider, event emitter). Deterministic code owns arithmetic, the eligibility gate, and payment; the offline simulator stands in for Grok behind the same `ReasoningProvider` protocol. Every state change goes through `ledger.py` (parameterized SQL, transition-checked) and is mirrored as a JSONL event.

**Tech Stack:** Python 3.12, uv, Pydantic v2, `sqlite3`, `decimal`, LangGraph 1.2.x (new dependency), `argparse`, `logging`, pytest, ruff.

**Spec:** `docs/tickets/P1-01-source-intake-and-txt-extraction.md` through `docs/tickets/P1-10-phase-1-end-to-end-tests.md`, with `docs/PRD.md` §5 and Phase 1, `docs/systemsdesign.md` (agent responsibilities, processing sequence, persistence), and the Phase 0 code in `src/invoice_processing/`.

## Global Constraints

- Money is `Decimal` only; floats rejected; JSON money is a string. Hashing and comparison across sources use `money.canonical_amount`.
- `HIGH_VALUE_THRESHOLD_USD = Decimal("10000.00")`: `≤ 10,000.00` may auto-pay, `> 10,000.00` waits in `awaiting_human_approval`.
- Only `USD` is payable. Any other currency routes to `needs_review`, never `rejected` and never paid.
- Model (or simulator) output never authorizes payment. `payments.pay` rereads persisted state and is the only caller of `mock_payment`.
- No payment retries anywhere. At most one payment row per invoice identity (DB `UNIQUE`).
- Offline mode imports no model SDK and opens no socket. Every simulated output's summary contains the text `offline simulation`.
- No function reads the system clock for business rules; `evaluation_date` is passed in. Timestamps for records are ISO-8601 UTC.
- stdout carries only the final result JSON. Events go to the JSONL file or stderr; the human summary and `mock_payment`'s print go to stderr.
- Logs never contain API keys, environment variables, full invoice text, or model reasoning.
- Tests use temporary databases only; never the repo-root `inventory.db`. Full suite under 30 s.
- Default `--mode` is `offline` — **pending user confirmation (P1-09 decision)**. Implement it behind one constant `DEFAULT_MODE` in `main.py` so a different answer is a one-line change.
- Ruff `E, F, I, UP, B`, line length 100. Tests assert codes, statuses, and values, never prose (except the literal `offline simulation` label and the CLI notices this plan fixes).

## Deliberate deviations from the tickets

- **Transition table lives in `transitions.py`, not `workflow.py`** (P1-07): `ledger.update_run_status` enforces it, and `ledger` must not import the graph (cycle). `workflow.py` re-exports it.
- **Intake runs in the service, not the ingestion node** (P1-06/P1-07): the run row needs the content hash and source row first, and duplicate detection happens before the graph. The ingestion node starts from the intaken `SourceDocument` + bytes.
- **`payment` and `outcome` are two nodes in `agents/payment.py`** (P1-06): `payment` executes only on `approved`; `outcome` records rejections and waiting states. This makes "payment unreachable unless approved" a graph-structure fact.
- **`SCHEMA_VERSION` 2 → 3** for the new `runs.prior_run_id` column (older databases are refused per the Phase 0 review fix; recreate with `seed --fresh` to a new path).

## Review Focus

1. A run left non-terminal by a crash (e.g. after payment commit, before `finish_run`) must be marked `failed`/`interrupted` on the next invocation, and rerunning the file must return the existing receipt without a second payment. Test in Task 9.
2. The same bytes under a different filename are the same source and must come back `duplicate`, not processed again. Test in Task 9.
3. INV-1001 saved with CRLF line endings, trailing spaces, or a UTF-8 BOM must extract identically (BOM is valid UTF-8; strip it, don't fail). Test in Task 2.
4. A path given with an uppercase extension (`INVOICE_1001.TXT`) or containing spaces must be accepted; a `.txt` that is actually a directory must fail before any record. Test in Task 2.
5. Nothing but the result JSON may reach stdout — `mock_payment`'s print, the init notice, and the mode banner included — so `python main.py ... | python -m json.tool` succeeds. Test in Task 10.

---

### Task 1: Phase 1 contracts, schema v3, network guard

**Files:**
- Modify: `src/invoice_processing/codes.py`, `src/invoice_processing/schemas.py`, `src/invoice_processing/storage.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_codes.py`, `tests/test_schemas.py`, `tests/test_storage.py`, `tests/test_network_guard.py`

**Interfaces:**
- Produces (codes): `FindingCode.currency_assumed_usd` (info), `FindingCode.model_disagreement` (warning), `FindingCode.non_usd_currency` (review); `HumanReviewAction(StrEnum)`: `approve`, `decline`; `TERMINAL_RUN_STATUSES: frozenset[RunStatus]` = `{paid_mock, rejected, needs_review, awaiting_human_approval, failed, duplicate}`; `BUSINESS_OUTCOMES: frozenset[RunStatus]` = `{paid_mock, rejected, needs_review, awaiting_human_approval}`. Each new code gets a `FINDING_DESCRIPTIONS` entry.
- Produces (schemas):
  - `ApprovalRecommendation(recommendation: Recommendation, reasons: list[str], cited_codes: list[FindingCode], summary: str, mode: ExecutionMode, provider: str, model: str)`
  - `Critique(agrees: bool, omissions: list[FindingCode], high_value: bool, revised_recommendation: Recommendation | None, summary: str, mode, provider, model)`
  - `GateResult(outcome: GateOutcome, rule_ids: list[str], findings: list[ValidationFinding])` — `findings` are only the ones the gate adds.
  - `HumanReview(invoice_id: str, version: int, action: HumanReviewAction, reviewer: str, reason: str, policy_version: str)`
  - `PaymentResult(payment_id: str, receipt: MockReceipt, created: bool)`
  - `ProcessingResult` gains `source_hash: str | None = None`, `prior_run_id: str | None = None`, `evaluation_date: date | None = None`.
- Produces (storage): `SCHEMA_VERSION = 3`; `runs.prior_run_id TEXT REFERENCES runs(run_id)`; `atomic(conn)` context manager — joins an open transaction, otherwise opens one via `write_transaction`.
- Produces (tests): autouse fixture `no_network` in `tests/conftest.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_codes.py
def test_phase1_codes_and_severities():
    assert DEFAULT_SEVERITY[C.currency_assumed_usd] is Severity.info
    assert DEFAULT_SEVERITY[C.model_disagreement] is Severity.warning
    assert DEFAULT_SEVERITY[C.non_usd_currency] is Severity.review
    assert set(FINDING_DESCRIPTIONS) == set(FindingCode)
    assert BUSINESS_OUTCOMES < TERMINAL_RUN_STATUSES
    assert RunStatus.failed not in BUSINESS_OUTCOMES

# tests/test_schemas.py — add one sample each of ApprovalRecommendation, Critique, GateResult,
# HumanReview, PaymentResult to SAMPLES (round-trip test covers them).

# tests/test_storage.py
def test_runs_have_prior_run_id(conn):
    assert "prior_run_id" in {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}

def test_atomic_joins_open_transaction(conn):
    with storage.write_transaction(conn):
        with storage.atomic(conn):
            conn.execute("INSERT INTO inventory VALUES ('X', 1)")
        assert conn.in_transaction
    assert not conn.in_transaction

def test_atomic_opens_and_rolls_back_alone(conn):
    with pytest.raises(RuntimeError):
        with storage.atomic(conn):
            conn.execute("INSERT INTO inventory VALUES ('X', 1)")
            raise RuntimeError
    assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0

# tests/test_network_guard.py
def test_network_is_blocked():
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.create_connection(("example.com", 80), timeout=1)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_codes.py tests/test_schemas.py tests/test_storage.py tests/test_network_guard.py`
Expected: FAIL (missing attributes / no guard).

- [ ] **Step 3: Implement**

Add the codes, enums, sets, contracts, and column above. Add `_REVIEW = {C.non_usd_currency}` to the `DEFAULT_SEVERITY` construction. `atomic`: `if conn.in_transaction: yield conn` else delegate to `write_transaction`. The `no_network` fixture monkeypatches `socket.socket.connect` and `socket.create_connection` to raise `RuntimeError("network access blocked in tests")`. AF_UNIX sockets are not used anywhere, so a blanket block is fine.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 5: Commit** — `feat: add Phase 1 contracts, schema v3, and test network guard`

---

### Task 2: Source intake, TXT parser, minimal normalization (P1-01)

**Files:**
- Create: `src/invoice_processing/intake.py`, `src/invoice_processing/parsers/__init__.py`, `src/invoice_processing/parsers/txt.py`, `src/invoice_processing/normalize.py`
- Test: `tests/test_intake.py`, `tests/test_parser_txt.py`, `tests/test_normalize.py`

**Interfaces:**
- Consumes: `SourceDocument`, `InvoiceDraft`, `DraftLine`, `ExtractionIssue`, `EvidenceRef`, `NormalizedInvoice`, `LineItem`, `StatedTotals`, `NormalizationEvent`, `ValidationFinding`, `parse_decimal`, `DEFAULT_SEVERITY`.
- Produces:
  - `intake.IntakeError(ValueError)` with `.code: str` in `{"not_found", "not_a_file", "unsupported_format"}`.
  - `intake.SUPPORTED_EXTENSIONS = {".txt"}` (Phase 2 extends it).
  - `intake.read_source(path: str | Path) -> tuple[SourceDocument, bytes]` — `source_id = "src-" + content_hash[:16]`, `content_hash` = SHA-256 hex of the bytes, `format = SourceFormat.txt`, `parser_version = parsers.txt.PARSER_VERSION`, `original_name = path.name`, `extracted_text = None`. Extension matched case-insensitively.
  - `parsers.txt.PARSER_VERSION = "txt-1"`; `parsers.txt.ExtractionError(ValueError)` with `.code` (`"txt_decode_error"`).
  - `parsers.txt.parse_txt(source: SourceDocument, data: bytes) -> InvoiceDraft` — decodes `utf-8-sig` with `errors="strict"` (invalid bytes raise `ExtractionError`); `splitlines()` handles CRLF.
  - `normalize.normalize(draft: InvoiceDraft) -> tuple[NormalizedInvoice, list[ValidationFinding]]`.
  - `normalize.parse_amount(raw: str) -> Decimal` — strips surrounding whitespace, one leading `$`, and thousands commas, then `parse_decimal`.
  - `normalize.vendor_key(name: str) -> str` — `" ".join(name.split()).casefold()`; `normalize.invoice_number_key(number: str) -> str` — `number.strip().upper()`.

**Parsing rules (TXT, Phase 1 layout only):**
- Labeled fields, case-sensitive labels, value after the first `:` stripped: `Vendor` → `vendor_raw`; `Invoice Number` → `invoice_number_raw`; `Date` → `invoice_date_raw`; `Due Date` → `due_date_raw`; `Subtotal` → `subtotal_raw`; `Total Amount` or `Total` → `total_raw`; `Tax (<rate>%)` → `tax_rate_raw = "<rate>"` (a percent string) and `tax_raw`; `Currency` → `currency_raw`. `Payment Terms` is recognized and ignored in Phase 1.
- Lines after `Items:` up to the first blank line match `^\s*(?P<name>\S+)\s+qty:\s*(?P<qty>\S+)\s+unit price:\s*(?P<price>\S+)\s*$` → `DraftLine`.
- Every value gets `EvidenceRef(source_id, location=f"line:{n}", snippet=<stripped line>)`, with 1-based line numbers.
- A blank line or the bare heading `INVOICE` is skipped. Any other line that matches nothing becomes `ExtractionIssue(code="unparsed_line", evidence=[line ref])`. Nothing is dropped silently.
- Currency: if no `Currency` label exists, and an amount carries a `$`, record the first `$` line as draft-level evidence `EvidenceRef(location=..., snippet=...)` in `draft.evidence`.

**Normalization rules:** ISO `YYYY-MM-DD` dates via `date.fromisoformat`; amounts via `parse_amount`; `tax_rate = Decimal(rate) / 100` (fraction, per `StatedTotals.tax_rate`); quantities via `parse_decimal`. A value that fails to parse stays `None` and adds a `NormalizationEvent(provenance="rule:unparseable", raw_value=raw, normalized_value=None)`. When `currency_raw` is `None` and `draft.evidence` has `$` evidence, set `currency="USD"`, add `NormalizationEvent(field="currency", raw_value=None, normalized_value="USD", provenance="rule:dataset_usd_assumption", evidence=draft.evidence)`, and return the finding `currency_assumed_usd` (info) with the same evidence. Set `vendor_key`/`invoice_number_key` only when the raw value is non-blank. Copy line evidence onto `LineItem.evidence`.

- [ ] **Step 1: Write the failing tests**

```python
FIXTURE = Path("data/invoices/invoice_1001.txt")

def test_inv_1001_end_to_end_extraction():
    source, data = read_source(FIXTURE)
    inv, findings = normalize(parse_txt(source, data))
    assert inv.vendor_name == "Widgets Inc." and inv.vendor_key == "widgets inc."
    assert inv.invoice_number == "INV-1001" and inv.invoice_number_key == "INV-1001"
    assert inv.due_date == date(2026, 2, 1) and inv.invoice_date == date(2026, 1, 15)
    assert [(l.item, l.quantity, l.unit_price) for l in inv.lines] == [
        ("WidgetA", Decimal("10"), Decimal("250.00")),
        ("WidgetB", Decimal("5"), Decimal("500.00")),
    ]
    assert inv.stated.subtotal == inv.stated.total == Decimal("5000.00")
    assert inv.stated.tax == Decimal("0.00") and inv.stated.tax_rate == Decimal("0")
    assert inv.currency == "USD"
    assert [f.code for f in findings] == [C.currency_assumed_usd]
    assert any(e.provenance == "rule:dataset_usd_assumption" for e in inv.normalization_events)

def test_every_extracted_value_has_line_evidence():
    draft = parse_txt(*read_source(FIXTURE))
    assert all(l.evidence and l.evidence[0].location.startswith("line:") for l in draft.lines)
    # field-level evidence: draft.evidence contains a "line:N" ref for vendor, number, dates, totals
    locations = {e.location for e in draft.evidence}
    assert {"line:3", "line:4", "line:5", "line:6", "line:12", "line:13", "line:14"} <= locations

def test_crlf_bom_and_trailing_spaces_extract_identically(tmp_path):  # Review Focus 3
    raw = FIXTURE.read_bytes().decode()
    variant = "﻿" + "\r\n".join(l + "  " for l in raw.splitlines())
    p = tmp_path / "v.txt"; p.write_bytes(variant.encode())
    a, _ = normalize(parse_txt(*read_source(FIXTURE)))
    b, _ = normalize(parse_txt(*read_source(p)))
    assert a.model_dump(exclude={"source_id", "lines", "normalization_events"}) == \
        b.model_dump(exclude={"source_id", "lines", "normalization_events"})
    assert [(l.item, l.quantity) for l in a.lines] == [(l.item, l.quantity) for l in b.lines]

def test_invalid_utf8_raises_extraction_error(tmp_path):
    p = tmp_path / "bad.txt"; p.write_bytes(b"Vendor: \xff\xfe\n")
    with pytest.raises(ExtractionError) as e:
        parse_txt(*read_source(p))
    assert e.value.code == "txt_decode_error"

def test_unparsed_line_becomes_issue(tmp_path): ...  # "Hello world" line → issues == [unparsed_line]

@pytest.mark.parametrize(("make", "code"), [
    (lambda d: d / "missing.txt", "not_found"),
    (lambda d: (d / "dir.txt").mkdir() or d / "dir.txt", "not_a_file"),
    (lambda d: (d / "a.docx").write_text("x") or d / "a.docx", "unsupported_format"),
])
def test_intake_errors(tmp_path, make, code): ...  # IntakeError.code == code

def test_uppercase_extension_and_spaces_accepted(tmp_path):  # Review Focus 4
    p = tmp_path / "my invoice 1001.TXT"; p.write_bytes(FIXTURE.read_bytes())
    assert read_source(p)[0].content_hash == read_source(FIXTURE)[0].content_hash

def test_parse_amount():
    assert parse_amount(" $5,000.00 ") == Decimal("5000.00")
    with pytest.raises(ValueError):
        parse_amount("five")
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_intake.py tests/test_parser_txt.py tests/test_normalize.py` → FAIL (modules missing).
- [ ] **Step 3: Implement** the three modules per the interfaces and rules above.
- [ ] **Step 4: Run** `uv run pytest` → PASS.
- [ ] **Step 5: Commit** — `feat: add source intake, TXT parser, and minimal normalization`

---

### Task 3: Run transitions and ledger writes (P1-02)

**Files:**
- Create: `src/invoice_processing/transitions.py`, `src/invoice_processing/ledger.py`
- Test: `tests/test_transitions.py`, `tests/test_ledger.py`

**Interfaces:**
- Consumes: `storage.atomic`, `storage.connect/init_schema`, `money.canonical_amount`, contracts from Task 1.
- Produces:
  - `transitions.RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]]`, exactly:
    - `received → {extracted, failed, duplicate}`
    - `extracted → {validated, failed}`
    - `validated → {approval_pending, failed}`
    - `approval_pending → {approved, rejected, needs_review, awaiting_human_approval, failed}`
    - `approved → {paid_mock, failed}`
    - every status in `TERMINAL_RUN_STATUSES → frozenset()`
  - `transitions.IllegalTransition(ValueError)`; `transitions.check(current: RunStatus, new: RunStatus) -> None`.
  - `ledger.utcnow() -> str` (ISO-8601 UTC, `Z` suffix; the only clock read, used for record timestamps).
  - `ledger.record_source(conn, source: SourceDocument) -> tuple[str, bool]` → `(source_id, already_existed)`; lookup by `content_hash`.
  - `ledger.upsert_invoice(conn, vendor_key: str | None, invoice_number_key: str | None, content_hash: str) -> str` → `invoice_id` (`"inv-" + uuid4().hex`). Blank or missing key → provisional `("pending", f"pending:{content_hash}")`. New rows start with `status="processing"`.
  - `ledger.semantic_hash(invoice: NormalizedInvoice) -> str` — SHA-256 of compact, sorted-key JSON of `{vendor_key, invoice_number_key, currency, due_date (iso or null), lines: sorted [[item, qty, unit_price]], total}`. `qty` is `f"{q.normalize():f}"`, and money uses `canonical_amount(…, currency)` (or `str()` when currency is unsupported or None). Excludes everything else.
  - `ledger.record_version(conn, invoice_id: str, invoice: NormalizedInvoice, source_id: str, origin: str = "extracted") -> tuple[str, int]` → `(version_id, version)`. If a version with the same semantic hash exists for the invoice, return it. Otherwise `version = max + 1`, insert `payload_json = invoice.model_dump_json()`, and set `invoices.current_version` unless `invoices.status == "paid_mock"`.
  - `ledger.start_run(conn, mode: ExecutionMode, source_id: str, evaluation_date: date) -> str` (`"run-" + uuid4().hex`, status `received`).
  - `ledger.attach_run(conn, run_id, invoice_id, version_id) -> None`.
  - `ledger.update_run_status(conn, run_id, status: RunStatus) -> None` — reads current status, `transitions.check`, updates `status` and `stage`.
  - `ledger.finish_run(conn, run_id, status: RunStatus, error_code: str | None = None, error_message: str | None = None, prior_run_id: str | None = None) -> None` — status must be in `TERMINAL_RUN_STATUSES`; a transition to `failed` is legal from any non-terminal state; sets `finished_at`.
  - `ledger.get_run_status(conn, run_id) -> RunStatus`.
  - `ledger.set_invoice_status(conn, invoice_id, status: InvoiceStatus) -> None` — a no-op when the current status is `paid_mock`.
  - `ledger.record_findings(conn, run_id, version_id: str | None, findings: list[ValidationFinding]) -> None`.
  - `ledger.record_decision(conn, run_id, version_id: str | None, decision: ApprovalDecision) -> None` — writes `final_decision = decision.final_decision`.
  - `ledger.get_human_review(conn, invoice_id, version: int, policy_version: str) -> HumanReview | None` — latest `approve`/`decline` row for that exact version and policy.
  - `ledger.append_audit_event(conn, run_id: str | None, stage: str, event: str, payload: dict, invoice_id: str | None = None, version_id: str | None = None) -> None` — `payload_json` sorted keys; strips keys matching the observability redaction rule (Task 6 owns the rule; until then define `REDACTED_KEY = re.compile(r"key|secret|token|password|authorization", re.I)` here, and Task 6 imports it from `ledger`).
  - `ledger.list_audit_events(conn, run_id) -> list[dict]` ordered by `event_id` (keys: `stage, event, payload, created_at`).
  - `ledger.PriorOutcome(run_id: str, status: RunStatus, invoice_id: str | None, receipt: MockReceipt | None)` (frozen dataclass).
  - `ledger.find_prior_outcome(conn, content_hash: str) -> PriorOutcome | None` — latest run (by `started_at`, then rowid) for that source whose status is in `BUSINESS_OUTCOMES` and `retry_of IS NULL`. Its receipt is the payment for the run's invoice, if any.
  - `ledger.mark_interrupted_runs(conn, started_before: str) -> list[str]` — every run not in `TERMINAL_RUN_STATUSES` with `started_at < started_before` → `failed`, `error_code="interrupted"`. Returns run IDs.
- Every write function uses `storage.atomic(conn)`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize(("cur", "new"), [
    (RunStatus.paid_mock, s) for s in RunStatus] + [
    (RunStatus.duplicate, RunStatus.paid_mock), (RunStatus.received, RunStatus.paid_mock),
    (RunStatus.validated, RunStatus.approved)])
def test_illegal_transitions_raise(cur, new): ...  # pytest.raises(IllegalTransition)

def test_happy_path_transitions_are_legal(): ...  # received→extracted→validated→approval_pending→approved→paid_mock

def test_record_source_twice_returns_one_row(conn): ...  # second call → (same id, True); COUNT(*)==1

def test_semantic_hash_ignores_filename_whitespace_and_line_order():
    a = inv_1001()  # tests/helpers.py builder, source_id="a"
    b = a.model_copy(update={"source_id": "b", "lines": list(reversed(a.lines)),
                             "vendor_name": "  Widgets   Inc. "})
    assert semantic_hash(a) == semantic_hash(b)
    c = a.model_copy(update={"lines": [a.lines[0].model_copy(update={"quantity": Decimal("11")}),
                                       a.lines[1]]})
    assert semantic_hash(a) != semantic_hash(c)
    d = a.model_copy(update={"stated": a.stated.model_copy(update={"total": Decimal("5E+3")})})
    assert semantic_hash(a) == semantic_hash(d)

def test_provisional_identities_differ_per_source(conn):
    i1 = upsert_invoice(conn, None, "INV-1009", "h1"); i2 = upsert_invoice(conn, "", None, "h2")
    assert i1 != i2
    assert conn.execute("SELECT vendor_key, invoice_number_key FROM invoices WHERE invoice_id=?",
                        (i1,)).fetchone()[:] == ("pending", "pending:h1")

def test_upsert_same_identity_returns_same_invoice(conn): ...

def test_record_version_dedupes_by_semantic_hash(conn): ...  # same invoice twice → same (id, 1)

def test_run_lifecycle_and_audit_order(conn):
    # start_run → update to extracted → append 3 audit events → finish_run(failed, "boom")
    # list_audit_events returns the 3 in insertion order; status failed; finished_at set

def test_finish_run_rejects_non_terminal(conn): ...  # finish_run(..., RunStatus.validated) raises

def test_audit_payload_redacts_secret_keys(conn):
    append_audit_event(conn, rid, "x", "y", {"api_key": "sk-1", "ok": 1})
    assert list_audit_events(conn, rid)[0]["payload"] == {"ok": 1}

def test_find_prior_outcome_skips_failed_runs(conn): ...  # failed run only → None; then a paid_mock run → found
def test_mark_interrupted_runs(conn): ...  # a run left at 'validated' → failed/interrupted
def test_set_invoice_status_never_leaves_paid_mock(conn): ...
```

Add `inv_1001()` to `tests/helpers.py` if missing. It is a builder with WidgetA 10 @ 250.00, WidgetB 5 @ 500.00, total 5000.00, USD, due 2026-02-01, vendor "Widgets Inc.", number "INV-1001", and keys set.

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_transitions.py tests/test_ledger.py` → FAIL.
- [ ] **Step 3: Implement** `transitions.py` and `ledger.py` per the interfaces.
- [ ] **Step 4: Run** `uv run pytest` → PASS.
- [ ] **Step 5: Commit** — `feat: add run transition table and ledger writes`

---

### Task 4: Reasoning interface and offline simulator (P1-03)

**Files:**
- Create: `src/invoice_processing/reasoning/__init__.py`, `reasoning/base.py`, `reasoning/offline.py`
- Test: `tests/test_reasoning_offline.py`

**Interfaces:**
- Consumes: `ApprovalRecommendation`, `Critique`, `Recommendation`, `NormalizedInvoice`, `ValidationFinding`, `Severity`.
- Produces:
  - `reasoning.base.PolicyContext(policy_version: str, high_value_threshold: Decimal)` (frozen dataclass). Built by `policy.context()` in Task 5; tests construct it directly.
  - `reasoning.base.ReasoningProvider` (`typing.Protocol`): `mode: ExecutionMode`, `provider: str`, `model: str`, `recommend(invoice, findings, policy: PolicyContext) -> ApprovalRecommendation`, `critique(invoice, findings, recommendation: ApprovalRecommendation, policy) -> Critique`, `assist_extraction(source_text: str, draft: InvoiceDraft) -> InvoiceDraft` (stub; the offline version returns `draft` unchanged).
  - `reasoning.offline.OfflineSimulator` with `mode=offline`, `provider="offline"`, `model="simulated"`.
    - `recommend`: `reject` if any `blocker`, else `review` if any `review`, else `approve`. `cited_codes` = codes of every blocker and review finding, in input order, without duplicates. `reasons` = one entry per cited code (`code.value`). `summary` starts with `"offline simulation: "`.
    - `critique`: `omissions` = blocker/review codes missing from `recommendation.cited_codes`. `high_value` = `invoice.stated.total is not None and > threshold`. `agrees = not omissions` and the recommendation is consistent with the findings (`reject` iff a blocker exists). When it disagrees, `revised_recommendation` = what `recommend` would return. The summary starts with `"offline simulation: "`.
  - `reasoning.ProviderUnavailable(RuntimeError)`; `reasoning.get_provider(mode: ExecutionMode | str) -> ReasoningProvider`. `offline` → `OfflineSimulator()`. `live` → raises `ProviderUnavailable("live mode is not available until Phase 3")`. Any other value → `ValueError`.

- [ ] **Step 1: Write the failing tests**

```python
POLICY = PolicyContext(policy_version="test", high_value_threshold=Decimal("10000.00"))

@pytest.mark.parametrize(("severities", "expected"), [
    ([], Recommendation.approve), ([Severity.warning], Recommendation.approve),
    ([Severity.review], Recommendation.review), ([Severity.review, Severity.blocker], Recommendation.reject)])
def test_recommendation_rule(severities, expected): ...

def test_deterministic_and_labeled():
    s = OfflineSimulator(); args = (inv_1001(), [], POLICY)
    assert s.recommend(*args) == s.recommend(*args)
    assert "offline simulation" in s.recommend(*args).summary

def test_critique_flags_omitted_blocker_and_revises():
    findings = [finding(C.zero_stock)]  # helper from tests/helpers.py
    bad = ApprovalRecommendation(recommendation=Recommendation.approve, reasons=[], cited_codes=[],
        summary="x", mode="offline", provider="offline", model="simulated")
    c = OfflineSimulator().critique(inv_1001(), findings, bad, POLICY)
    assert not c.agrees and c.omissions == [C.zero_stock]
    assert c.revised_recommendation is Recommendation.reject

def test_critique_flags_high_value(): ...  # total 10000.01 → high_value True, agrees True

def test_get_provider_live_fails_without_fallback():
    with pytest.raises(ProviderUnavailable):
        get_provider("live")

def test_offline_provider_imports_no_model_sdk():
    code = "import sys, invoice_processing.reasoning as r; r.get_provider('offline'); " \
           "print(any(m.split('.')[0] in {'xai_sdk','openai','anthropic','httpx'} for m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": "src"}, check=True).stdout.strip()
    assert out == "False"
```

`finding(code)` builder: add it to `tests/helpers.py` (code plus its default severity) if absent.

- [ ] **Step 2: Fail** → **Step 3: Implement** → **Step 4: Pass** (`uv run pytest`)
- [ ] **Step 5: Commit** — `feat: add reasoning provider protocol and offline simulator`

---

### Task 5: Deterministic eligibility gate (P1-04)

**Files:**
- Create: `src/invoice_processing/policy.py`
- Test: `tests/test_policy.py`

**Interfaces:**
- Consumes: `GateResult`, `GateOutcome`, `HumanReview`, `HumanReviewAction`, `Recommendation`, `PolicyContext`, `FindingCode`, `DEFAULT_SEVERITY`.
- Produces:
  - `POLICY_VERSION = "2026-11-01.1"`; `HIGH_VALUE_THRESHOLD_USD = Decimal("10000.00")`; `context() -> PolicyContext`.
  - `evaluate(invoice: NormalizedInvoice, findings: list[ValidationFinding], recommendation: Recommendation, human_review: HumanReview | None = None, *, version: int | None = None) -> GateResult`.

**Rules, first match wins** (rule IDs are exact strings):
1. `R1_blocker`: any finding with severity `blocker` → `rejected`.
2. `R2_non_usd`: `invoice.currency != "USD"` → `needs_review`, and the gate adds a `non_usd_currency` finding (`observed=currency`). `R2_review`: any `review` finding → `needs_review`. When both apply, `rule_ids` lists both.
3. Let `approved_by_human` = `human_review` is not None, `action == approve`, `policy_version == POLICY_VERSION`, `version is not None`, and `human_review.version == version`. `R3_high_value`: `stated.total > HIGH_VALUE_THRESHOLD_USD`. `R3_model_disagreement`: `recommendation != approve`; the gate adds a `model_disagreement` finding. If either applies and not `approved_by_human` → `awaiting_human_approval`.
4. `R4_auto_approve` (total ≤ threshold, recommendation approve) or `R4_human_approved` → `approved`.

A `decline` review never approves. A human review never clears rule 1 or rule 2.

- [ ] **Step 1: Write the failing table-driven test**

```python
HR = lambda version=1, action="approve", pv=POLICY_VERSION: HumanReview(
    invoice_id="i", version=version, action=action, reviewer="vp", reason="ok", policy_version=pv)

CASES = [  # (id, total, currency, finding_codes, recommendation, human_review, outcome, rule_ids)
    ("clean_10000.00", "10000.00", "USD", [], "approve", None, "approved", ["R4_auto_approve"]),
    ("clean_10000.01", "10000.01", "USD", [], "approve", None, "awaiting_human_approval", ["R3_high_value"]),
    ("hv_with_review", "10000.01", "USD", [], "approve", HR(), "approved", ["R4_human_approved"]),
    ("hv_wrong_version", "10000.01", "USD", [], "approve", HR(version=2), "awaiting_human_approval", ["R3_high_value"]),
    ("hv_wrong_policy", "10000.01", "USD", [], "approve", HR(pv="old"), "awaiting_human_approval", ["R3_high_value"]),
    ("hv_declined", "10000.01", "USD", [], "approve", HR(action="decline"), "awaiting_human_approval", ["R3_high_value"]),
    ("blocker_approve", "5000.00", "USD", ["zero_stock"], "approve", None, "rejected", ["R1_blocker"]),
    ("blocker_human", "5000.00", "USD", ["zero_stock"], "approve", HR(), "rejected", ["R1_blocker"]),
    ("eur_clean", "4125.50", "EUR", [], "approve", None, "needs_review", ["R2_non_usd"]),
    ("eur_human", "4125.50", "EUR", [], "approve", HR(), "needs_review", ["R2_non_usd"]),
    ("model_reject_clean", "5000.00", "USD", [], "reject", None, "awaiting_human_approval", ["R3_model_disagreement"]),
    ("model_reject_human", "5000.00", "USD", [], "reject", HR(), "approved", ["R4_human_approved"]),
    ("warning_only", "5000.00", "USD", ["due_date_past"], "approve", None, "approved", ["R4_auto_approve"]),
]

@pytest.mark.parametrize(CASE_FIELDS, CASES, ids=[c[0] for c in CASES])
def test_gate(...):
    result = evaluate(inv, findings, Recommendation(rec), hr, version=1)
    assert result.outcome == outcome and result.rule_ids == rule_ids

def test_gate_adds_disagreement_and_currency_findings(): ...  # codes in result.findings
```

- [ ] **Step 2: Fail** → **Step 3: Implement** → **Step 4: Pass**
- [ ] **Step 5: Commit** — `feat: add deterministic eligibility policy gate`

---

### Task 6: Structured logging and result output (P1-08)

**Files:**
- Create: `src/invoice_processing/observability.py`
- Test: `tests/test_observability.py`

**Interfaces:**
- Consumes: `ProcessingResult`, `ledger.REDACTED_KEY`.
- Produces:
  - `EVENT_FIELDS = ("ts", "run_id", "stage", "event", "status", "mode", "source_hash", "duration_ms", "codes")`.
  - `JsonLineFormatter(logging.Formatter)`: emits one JSON object per record. Fields come from `record.event_data: dict`, and `ts` is the record time in UTC ISO. Any key matching `REDACTED_KEY` is dropped (recursively in nested dicts). Unknown keys are allowed.
  - `configure_events(path: Path | None) -> logging.Logger`: returns logger `invoice_processing.events` with `propagate=False` and exactly one handler. That handler is a `FileHandler` (parent dirs created) when a path is given, else stderr. Calling it again replaces the handler.
  - `log_event(logger, *, run_id: str | None, stage: str, event: str, **fields) -> None`.
  - `stage_timer() -> ContextManager[dict]`: yields a dict and sets `"duration_ms": int` on exit (via `time.perf_counter`).
  - `write_result(result: ProcessingResult, out: Path | TextIO | None = None) -> None`: writes `result.model_dump_json(indent=2)` plus a newline to the path, or to the stream (default `sys.stdout`).
  - `format_summary(result: ProcessingResult) -> str`: a short human summary of status, invoice, and receipt amount via `format_money`, intended for stderr.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_event_line_is_json_with_run_id_and_stage(tmp_path):
    lg = configure_events(tmp_path / "e.jsonl")
    log_event(lg, run_id="r1", stage="ingestion", event="extracted", status="extracted", codes=[])
    log_event(lg, run_id="r1", stage="payment", event="paid", duration_ms=3)
    lines = (tmp_path / "e.jsonl").read_text().splitlines()
    assert len(lines) == 2 and all({"run_id", "stage", "ts"} <= json.loads(l).keys() for l in lines)

def test_redaction(tmp_path):
    lg = configure_events(tmp_path / "e.jsonl")
    log_event(lg, run_id="r", stage="s", event="e", api_key="sk-secret", nested={"auth_token": "t"})
    text = (tmp_path / "e.jsonl").read_text()
    assert "sk-secret" not in text and "auth_token" not in text

def test_write_result_money_as_strings(capsys): ...  # receipt amount "5000.00" as a JSON string
def test_stage_timer_sets_duration(): ...
def test_output_paths_are_gitignored():
    out = subprocess.run(["git", "check-ignore", "output/events.jsonl", "output/result.json"],
                         capture_output=True, text=True)
    assert out.returncode == 0
```

- [ ] **Step 2: Fail** → **Step 3: Implement** → **Step 4: Pass**
- [ ] **Step 5: Commit** — `feat: add JSONL event logging and result output`

---

### Task 7: Guarded, idempotent mock payment (P1-05)

**Files:**
- Create: `src/invoice_processing/payments.py`
- Test: `tests/test_payments.py`

**Interfaces:**
- Consumes: `storage.write_transaction`, `ledger.append_audit_event`, `ledger.get_human_review`, `policy.POLICY_VERSION`, `policy.HIGH_VALUE_THRESHOLD_USD`, `money.canonical_amount`, `MockReceipt`, `PaymentResult`.
- Produces:
  - `mock_payment(vendor: str, amount: Decimal, currency: str) -> dict`: prints `Paying {vendor} {format_money(amount, currency)}` **to stderr** and returns `{"status": "success"}`. This mirrors the assignment's API; stderr keeps stdout JSON-only.
  - `PaymentNotAuthorized(RuntimeError)` with `.reason: str`.
  - `pay(conn, invoice_id: str, version_id: str, run_id: str) -> PaymentResult`. Opens `storage.write_transaction(conn)` itself (`BEGIN IMMEDIATE`), so it must be called outside any transaction. Then, in order:
    1. If a `payments` row exists for `invoice_id`, return `PaymentResult(created=False, …)` from that row. Do not call `mock_payment`.
    2. Read the `decisions` row for `run_id`. It must exist with `final_decision == "approved"` and `version_id` equal to the argument; otherwise raise `PaymentNotAuthorized("not_approved")`.
    3. Load `invoice_versions.payload_json` → `NormalizedInvoice`. It must have `currency == "USD"` (else `"not_usd"`) and `stated.total` (else `"no_total"`).
    4. If total > threshold, or the run has a `model_disagreement` finding, `ledger.get_human_review(conn, invoice_id, version, POLICY_VERSION)` must return `approve`; otherwise raise `"human_approval_required"`.
    5. Call `mock_payment(invoice.vendor_name, total, "USD")`. Any non-`success` status raises `"mock_payment_failed"`.
    6. Insert the payment: `payment_id = "pay-" + uuid4().hex`, `receipt_id = "rcpt-" + uuid4().hex[:12]`, `amount = canonical_amount(total, "USD")`, `status = "success"`. Append the audit event `stage="payment", event="payment_succeeded"` with `{receipt_id, amount, currency}`. The commit happens on context exit.
  - `record_rejection(conn, run_id: str, invoice_id: str | None, version_id: str | None, codes: list[FindingCode]) -> None`: appends the audit event `payment` / `rejection_recorded` with `{"codes": [...]}`. Never calls `mock_payment`.

- [ ] **Step 1: Write the failing tests**

Fixture `approved_run(conn, total="5000.00", outcome="approved")`: seeds the source, invoice, version (`inv_1001`-style payload with that total), run, and a decision row with `final_decision=outcome`. Returns `(invoice_id, version_id, run_id)`.

```python
def test_pay_twice_same_receipt_one_call(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(payments, "mock_payment", lambda *a: calls.append(a) or {"status": "success"})
    ids = approved_run(conn)
    first, second = payments.pay(conn, *ids), payments.pay(conn, *ids)
    assert first.created and not second.created
    assert first.receipt.receipt_id == second.receipt.receipt_id and len(calls) == 1
    assert first.receipt.amount == Decimal("5000.00")

@pytest.mark.parametrize("outcome", ["rejected", "needs_review", "awaiting_human_approval"])
def test_non_approved_raises_no_payment(conn, outcome): ...  # PaymentNotAuthorized; 0 payment rows

def test_high_value_without_human_review_raises(conn): ...  # total 10000.01, decision approved → "human_approval_required"
def test_high_value_with_matching_review_pays(conn): ...    # insert human_reviews approve v1 + POLICY_VERSION

def test_failure_inside_transaction_leaves_nothing(conn, monkeypatch):
    monkeypatch.setattr(payments.ledger, "append_audit_event",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        payments.pay(conn, *approved_run(conn))
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
    assert not [e for e in ledger_events(conn) if e["event"] == "payment_succeeded"]

def test_mock_payment_prints_to_stderr_only(capsys): ...  # out == "" and "USD 5,000.00" in err
def test_record_rejection_never_pays(conn, monkeypatch): ...
```

- [ ] **Step 2: Fail** → **Step 3: Implement** → **Step 4: Pass**
- [ ] **Step 5: Commit** — `feat: add guarded idempotent mock payment service`

---

### Task 8: Agent nodes (P1-06)

**Files:**
- Create: `src/invoice_processing/agents/__init__.py`, `agents/state.py`, `agents/ingestion.py`, `agents/validation.py`, `agents/approval.py`, `agents/payment.py`
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: Tasks 2–7.
- Produces:
  - `agents.state.InvoiceState(TypedDict, total=False)`: `run_id: str`, `mode: ExecutionMode`, `evaluation_date: date`, `source: SourceDocument`, `raw: bytes`, `invoice: NormalizedInvoice`, `invoice_id: str`, `version_id: str`, `version: int`, `findings: list[ValidationFinding]`, `decision: ApprovalDecision`, `gate: GateResult`, `receipt: MockReceipt`, `status: RunStatus`, `error_code: str`, `error_message: str`.
  - `agents.state.Deps` (dataclass): `conn: sqlite3.Connection`, `provider: ReasoningProvider`, `events: logging.Logger`.
  - `agents.state.emit(deps, state, stage: str, event: str, **payload) -> None`: writes `ledger.append_audit_event` and `observability.log_event`. The event carries `status`, `mode`, `source_hash` (from `state["source"].content_hash`), and `codes` when given. This is the single way nodes record activity.
  - Each node is `(state: InvoiceState, deps: Deps) -> dict` (a partial state update) and advances the run via `ledger.update_run_status`:
    - `ingestion.run(state, deps)`: `parse_txt` → `normalize` → `upsert_invoice` → `record_version` → `attach_run` → status `extracted`. The update includes the normalization findings in `findings`. On `ExtractionError`, return `{"status": failed, "error_code": e.code}` and do not update the run status; the service finishes the run.
    - `validation.run(state, deps)`: `check_required_fields + check_value_signs + check_due_date(evaluation_date) + reconcile_totals + aggregate_quantities/check_inventory_against_db`. Normalization findings are kept first. Stores the computed totals on the invoice (`invoice.model_copy(update={"computed": …})`). Calls `record_findings`, sets status `validated`, and only reads inventory.
    - `approval.run(state, deps)`: status `approval_pending`, then `recommend`, then exactly one `critique`, then `final = critique.revised_recommendation or initial`, so there is at most one revision. Next, `policy.evaluate(invoice, findings, final, ledger.get_human_review(...), version=state["version"])`. The gate's findings are appended and recorded. Builds `ApprovalDecision(initial_recommendation, critique_summary, revised_recommendation, final_decision=gate.outcome, reasons=gate.rule_ids, policy_version, mode, provider, model)`, then `record_decision`, then sets status to the gate outcome. Emits `recommendation`, `critique`, `decision` events, with `policy_version` in the decision event.
    - `payment.pay_node(state, deps)`: the only importer of `payments.pay`. Calls it, sets status `paid_mock`, and returns `receipt`.
    - `payment.outcome_node(state, deps)`: for `rejected`, calls `payments.record_rejection` with the blocker codes. For waiting states, emits a `waiting` event. Never pays.

- [ ] **Step 1: Write the failing tests**

Each node is tested in isolation from a constructed state on a seeded temp DB (`seed.seed_inventory`).

```python
def test_ingestion_extracts_inv_1001(deps, received_state): ...  # status extracted; version 1; findings == [currency_assumed_usd]
def test_ingestion_decode_error_returns_failed(deps, received_state_bad_bytes): ...
def test_validation_does_not_write_inventory(deps, extracted_state):
    before = dict(deps.conn.execute("SELECT item, stock FROM inventory").fetchall())
    validation.run(extracted_state, deps)
    assert dict(deps.conn.execute("SELECT item, stock FROM inventory").fetchall()) == before
def test_approval_one_critique_at_most_one_revision(deps, validated_state, monkeypatch):
    # wrap provider.critique / recommend with counters; critique called exactly once, recommend once
def test_approval_inv_1001_is_approved(deps, validated_state): ...  # gate.outcome approved, rule R4_auto_approve
def test_outcome_node_rejected_never_pays(deps, monkeypatch): ...
def test_only_payment_module_imports_pay():
    for path in Path("src/invoice_processing").rglob("*.py"):
        if path.name != "payments.py" and path != Path("src/invoice_processing/agents/payment.py"):
            assert "payments import pay" not in path.read_text() and "payments.pay(" not in path.read_text()
```

- [ ] **Step 2: Fail** → **Step 3: Implement** → **Step 4: Pass**
- [ ] **Step 5: Commit** — `feat: add ingestion, validation, approval, and payment agent nodes`

---

### Task 9: LangGraph workflow and processing service (P1-07)

**Files:**
- Modify: `pyproject.toml`, `uv.lock`, `requirements.lock` (via `uv add "langgraph>=1.2,<2"`, then `uv export --format requirements-txt --no-hashes > requirements.lock`)
- Create: `src/invoice_processing/workflow.py`, `src/invoice_processing/service.py`
- Test: `tests/test_workflow.py`, `tests/test_service.py`

**Interfaces:**
- Consumes: Tasks 2–8. Before writing code, read the installed version's `StateGraph`/`add_conditional_edges` signatures (`uv run python -c "import langgraph, inspect; …"`). Don't rely on memory.
- Produces:
  - `workflow.RUN_TRANSITIONS`, re-exported from `transitions`.
  - `workflow.route_after(state) -> str`: `"end"` if status is `failed`, else the next node name.
  - `workflow.route_after_approval(state) -> Literal["payment", "outcome", "end"]`: `approved → "payment"`, `failed → "end"`, everything else → `"outcome"`.
  - `workflow.build_graph(deps: Deps, start: Literal["ingestion", "validation"] = "ingestion")`: a compiled `StateGraph(InvoiceState)` with nodes `ingestion, validation, approval, payment, outcome` bound to `deps` via `functools.partial`. Edges: `START → start`, `ingestion -(route_after)→ validation|END`, `validation -(route_after)→ approval|END`, `approval -(route_after_approval)→ payment|outcome|END`, `payment → END`, `outcome → END`. With `start="validation"`, the `ingestion` node is not added.
  - `service.process_invoice(path: str | Path, mode: ExecutionMode, db_path: str | Path, evaluation_date: date, events: logging.Logger | None = None) -> ProcessingResult`:
    1. `intake.read_source(path)`. `IntakeError` propagates and no run is created (the CLI maps it to a usage error).
    2. `connect` and `init_schema`, then `ledger.mark_interrupted_runs(conn, started_before=ledger.utcnow())`.
    3. `record_source`, then `start_run`, then emit `stage="intake", event="received"` (payload: `source_hash`, `original_name`, `mode`). Service-level events (`duplicate`, `finished`, `failed`) use `stage="service"`; Task 8's `emit` must tolerate a state with no `source` (the `start="validation"` path) by sending `source_hash=None`. If `find_prior_outcome(content_hash)` returns a prior outcome: `finish_run(duplicate, prior_run_id=…)`, emit `duplicate`, and return `ProcessingResult(status=duplicate, prior_run_id, receipt=prior.receipt, invoice_id=prior.invoice_id, …)`. The graph is not invoked and `invoices.status` is untouched.
    4. Otherwise `build_graph(Deps(conn, get_provider(mode), events)).invoke(initial_state)`.
    5. Terminal handling: `finish_run(status, error_code)`. Unless the status is `duplicate`, call `set_invoice_status` when an invoice exists. Emit `finished`.
    6. Any unexpected exception after run creation becomes `finish_run(failed, error_code="unexpected_error", error_message=type(e).__name__)`, and returns the `failed` result. No partial payment is possible, because `pay` is atomic.
    7. The result carries `source_hash`, `evaluation_date`, `findings`, `decision`, `receipt`, and `timings_ms` per stage.

- [ ] **Step 1: Write the failing tests**

```python
def test_inv_1001_offline_paid(tmp_path):
    r = process_invoice(FIXTURE, ExecutionMode.offline, tmp_db(tmp_path), EVAL)
    assert r.status is RunStatus.paid_mock and r.receipt.amount == Decimal("5000.00")
    assert r.receipt.currency == "USD"

def test_rerun_is_duplicate_one_payment(tmp_path):
    db = tmp_db(tmp_path); first = process_invoice(FIXTURE, OFF, db, EVAL)
    second = process_invoice(FIXTURE, OFF, db, EVAL)
    assert second.status is RunStatus.duplicate and second.prior_run_id == first.run_id
    assert second.receipt.receipt_id == first.receipt.receipt_id
    c = connect(db)
    assert c.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
    assert c.execute("SELECT status FROM invoices").fetchone()[0] == "paid_mock"

def test_same_bytes_new_filename_is_duplicate(tmp_path): ...  # Review Focus 2

def test_failed_then_rerun_is_normal(tmp_path, monkeypatch):
    # first: monkeypatch agents.validation.run to raise → status failed, 0 payments
    # second (patch removed): status paid_mock, not duplicate

def test_injected_validation_exception_fails_without_payment(tmp_path, monkeypatch): ...

def test_interrupted_run_then_rerun_does_not_pay_twice(tmp_path, monkeypatch):  # Review Focus 1
    # make ledger.finish_run raise once *after* pay committed → simulate crash (catch in test)
    # next process_invoice: earlier run marked failed/interrupted; result paid_mock with the
    # SAME receipt (pay returns existing); payments count == 1

def test_payment_unreachable_unless_approved():
    for status in RunStatus:
        assert (route_after_approval({"status": status}) == "payment") == (status is RunStatus.approved)
    g = build_graph(fake_deps()).get_graph()
    assert {e.source for e in g.edges if e.target == "payment"} == {"approval"}

def test_start_at_validation(tmp_path): ...  # build_graph(..., start="validation") on an extracted state reaches paid_mock
```

- [ ] **Step 2: Fail** → **Step 3: `uv add` langgraph, export the lock, implement** → **Step 4: Pass** (`uv run pytest`)
- [ ] **Step 5: Commit** — `feat: add LangGraph workflow and shared processing service`

---

### Task 10: CLI entry point (P1-09)

**Files:**
- Create: `main.py` (repo root)
- Modify: `docs/development.md` (Run section with examples)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `service.process_invoice`, `observability.configure_events/write_result/format_summary`, `reasoning.get_provider`, `ProviderUnavailable`, `IntakeError`, `storage`, `seed.seed_inventory`.
- Produces: `main.DEFAULT_MODE = "offline"` (pending confirmation), `main.build_parser() -> argparse.ArgumentParser`, and `main.main(argv: list[str] | None = None) -> int`.

**Behavior:**
- Options: `--invoice_path`/`--invoice-path` (required, `dest="invoice_path"`), `--mode {offline,live}` (default `DEFAULT_MODE`), `--db` (default `inventory.db`), `--output` (default stdout), `--events` (default `output/events.jsonl`), `--evaluation-date YYYY-MM-DD` (default `date.today()`, the CLI being the one place that reads the clock). Every option has `help=`.
- First, `get_provider(mode)`. If it raises `ProviderUnavailable`, print `error: live mode is not available until Phase 3` to stderr and return `2`. No database is touched.
- Print `Mode: offline simulation` (or `Mode: live`) to stderr.
- If the db file is missing or `PRAGMA user_version == 0`: `init_schema` plus `seed_inventory`, and print `Initialized <path> and seeded inventory` to stderr.
- `IntakeError` or a bad date → stderr message, return `2`. Otherwise `write_result` to `--output`/stdout, print `format_summary` to stderr, and return `1` if the status is `failed`, else `0`.
- `if __name__ == "__main__": sys.exit(main())`.

- [ ] **Step 1: Write the failing tests** (in-process via `main.main([...])` with `capsys`, temp `--db` and `--events`)

```python
def test_bare_command_pays_and_stdout_is_pure_json(tmp_path, capsys):  # Review Focus 5
    code = main.main(["--invoice_path=data/invoices/invoice_1001.txt", f"--db={tmp_path/'i.db'}",
                      f"--events={tmp_path/'e.jsonl'}", "--evaluation-date=2026-01-20"])
    out, err = capsys.readouterr()
    assert code == 0 and json.loads(out)["status"] == "paid_mock"
    assert "Mode: offline simulation" in err and "Initialized" in err

def test_second_run_no_init_notice_and_duplicate(tmp_path, capsys): ...  # "Initialized" not in err; status duplicate; exit 0
def test_dash_spelling_accepted(tmp_path, capsys): ...
def test_live_mode_fails_clearly_and_touches_nothing(tmp_path, capsys):
    code = main.main([..., "--mode=live"]); _, err = capsys.readouterr()
    assert code == 2 and "not available" in err and not (tmp_path / "i.db").exists()
def test_missing_file_is_usage_error(tmp_path, capsys): ...  # exit 2, no db created
def test_failed_run_exits_nonzero(tmp_path, capsys): ...  # invalid-UTF-8 copy → exit 1, status failed
def test_help_lists_every_option(capsys):
    with pytest.raises(SystemExit): main.main(["--help"])
    out = capsys.readouterr().out
    for opt in ["--invoice_path", "--mode", "--db", "--output", "--events", "--evaluation-date"]:
        assert opt in out
```

- [ ] **Step 2: Fail** → **Step 3: Implement**, and add a "Run" section to `docs/development.md` with the bare command, `--mode`, `--db`, `--output`, and `| python -m json.tool` → **Step 4: Pass**
- [ ] **Step 5: Commit** — `feat: add CLI entry point`

---

### Task 11: End-to-end tests and Phase 1 exit (P1-10)

**Files:**
- Create: `tests/test_e2e.py`
- Modify: `docs/tickets/P1-*.md` (status lines), `docs/tickets/README.md` (Phase 1 table), `docs/PRD.md` (Phase 1 checkboxes with test names)

**Interfaces:**
- Consumes: `main.py` as a subprocess. Helper `run_cli(*args, db, events) -> (CompletedProcess, dict | None)` runs `[sys.executable, "main.py", ...]` with `cwd=REPO_ROOT` and `env={**os.environ, "PYTHONPATH": "src"}`. This works even when the editable install is broken by the iCloud hidden-flag issue.

- [ ] **Step 1: Write the tests**

```python
def test_e2e_inv_1001_paid(tmp_path): ...       # status paid_mock; receipt amount "5000.00", currency USD
def test_e2e_rerun_duplicate(tmp_path): ...     # second subprocess → duplicate; sqlite payments COUNT == 1
def test_e2e_restart_same_db(tmp_path): ...     # new process, same db, different filename copy → still 1 payment
def test_e2e_corrupt_utf8_fails(tmp_path): ...  # returncode 1; status failed; 0 payments
def test_e2e_audit_trail(tmp_path):
    # events for the run (ledger.list_audit_events) in order cover stages
    # ["intake", "ingestion", "validation", "approval", "payment", "service"];
    # some payload carries source_hash, mode == "offline", policy_version, receipt_id
def test_e2e_never_touches_repo_db(tmp_path):
    before = Path("inventory.db").stat().st_mtime if Path("inventory.db").exists() else None
    run_cli(... db=tmp_path / "i.db" ...)
    after = Path("inventory.db").stat().st_mtime if Path("inventory.db").exists() else None
    assert before == after
```

The `no_network` fixture from Task 1 applies to the test process. For subprocesses, set `env["INVOICE_NETWORK_GUARD"]="1"` and add a tiny `sitecustomize`-free guard: `main.py` installs the same socket patch when that variable is set. Document that this variable is test-only.

- [ ] **Step 2: Run** `uv run pytest` → all pass with the guard active. Then `time uv run pytest` → under 30 s.
- [ ] **Step 3: Clean-clone check** (from the scratchpad, not the repo): `git clone <repo> p1check && cd p1check && uv sync && uv run pytest && uv run python main.py --invoice_path=data/invoices/invoice_1001.txt --db check.db | python -m json.tool`. Expected: tests pass, `"status": "paid_mock"`. Delete `p1check` afterwards.
- [ ] **Step 4: Mark done**: P1-01–P1-10 `Status: done`; Phase 1 rows in the ticket index set to `done`; PRD Phase 1 boxes ticked with the names of the e2e tests that prove each one.
- [ ] **Step 5: Commit** — `docs: mark Phase 1 complete`
