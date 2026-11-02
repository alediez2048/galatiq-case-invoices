# Phase 4 — Human Review Workflow (Service Layer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tasks marked **[SDD]** get an implementer, a task review and a fix loop; tasks marked **[light]** get one implementer and are covered only by the final whole-branch review (user decision 2026-11-01: full review only for payment eligibility, approvals, version/staleness checks and immutability).

**Goal:** evidence-backed corrections, high-value approve/decline and corrected-invoice submissions work end to end through the shared Python service, bound to versions, so that no human action can override a blocker, pay a stale version or pay an identity twice.

**Architecture:** a new `review.py` service owns every review action (`submit_correction`, `approve`, `decline`, `submit_corrected_invoice`, `allowed_actions`, `list_queue`). Each action checks the expected version and status inside one `BEGIN IMMEDIATE` write, records an immutable row (`corrections` / `human_reviews`), creates a new run linked to the run it continues, and commits; the run is then executed outside that transaction by `service.run_existing_version`, which enters the LangGraph workflow at `validation`. Corrections run the normal agent approval node (recommend → critique → revise, then the gate). Approve/decline run a new `approval.resume` node that makes no model call: it reuses the waiting run's recommendation and passes the human review to the gate. `policy.evaluate` and `payments.pay` stay the only deciders; `pay` also refuses any version that is not the invoice's current one. SQLite triggers make history immutable.

**Tech Stack:** Python 3.12, uv, Pydantic 2, SQLite (triggers), LangGraph 1.2, pytest, ruff. No new dependencies.

**Spec:** `docs/PRD.md` (Phase 4), `docs/decisions.md` (round 2 #2–#3, round 3 #1–#2, round 4, round 5 #3–#5), `docs/requirements.md` (business policy, P13, P14, evaluation and completion), `docs/systemsdesign.md` (core data contracts, persistence and transaction boundaries, revision policy), `docs/contraints.md` (operational bounds, trust boundaries), `docs/limitations.md` (rows 4, 6, 9), `docs/mockup.md` (screens 6–7), tickets `docs/tickets/P4-01`, `P4-02`, `P4-04`, `P4-05`, `P4-07`, and the P4-01 / P4-04 carry-over rows in `docs/tickets/README.md`. Builds on the Phase 3 interfaces in `docs/superpowers/plans/2026-11-01-phase-3-live-grok.md`.

**Out of scope (cut line, user decision 2026-11-01):** P4-03 identity corrections (any correction that would change the vendor key or invoice-number key is refused), P4-06 review CLI, and the thread-concurrency tests in P4-04 / P4-03.

## Global Constraints

- Offline outcomes for all 20 files in `data/invoices/` stay exactly as `tests/test_acceptance.py::CASES` asserts; no existing test changes its expected status.
- Human approval never overrides a `blocker` or `review` finding: `policy.evaluate` keeps the order R1 blocker → R2 review / non-USD → R3 high value / model disagreement → R4 approve.
- A human review counts only when its `invoice_id`, `version` and `policy_version` all match the version being paid; `payments.pay` refuses any version that is not `invoices.current_version` (`stale_version`).
- A correction or corrected submission creates a new version; it never edits source bytes, `sources` rows or earlier version payloads. Every correction reruns validation and the approval/critique workflow.
- One payment per invoice identity (`payments.invoice_id UNIQUE` stays the final guard); repeated actions return the existing outcome.
- EUR and other non-USD invoices are review-only and no human action can pay them (decisions round 5 #3).
- Corrected submissions supersede only when no version is paid, approved or awaiting human approval, and only through the explicit corrected-invoice action with a required reason; a plain upload stays `version_conflict` (decisions round 5 #5).
- Reviewer identity is a free-text local name (1–100 characters after stripping), recorded for audit; it is not authentication. Reasons are required (1–1,000 characters after stripping).
- No review action holds a database transaction open across a model call or while waiting for a human.
- Tests need no credentials and no network (autouse `no_network` guard); live-mode paths use `tests/fakes/xai_client.py`.
- Money stays `Decimal`; refusal and finding codes are stable identifiers; tests assert codes and statuses, not prose.
- `uv run ruff check .` and `uv run ruff format --check .` clean; commits end with the session trailer lines.

## Decisions taken in this plan

Each one settles something the tickets leave open. The cost if it is wrong comes after it.

1. **Process (user decision):** [SDD] for Tasks 1–4 (immutability, versions, corrections, approvals, supersede), [light] for Task 5 (acceptance sequences and docs). Cost: Task 5 relies on the final review. Any fix it forces in a payment module gets its own review.
2. **Immutability vs the Phase 3 payment re-point.** Triggers reject `DELETE` on `sources`, `invoice_versions`, `corrections`, `human_reviews`, `payments`, `audit_events`, `findings` and `decisions`, and reject `UPDATE` on them except in three narrow cases: (a) `invoice_versions.version_status` from `current` to `superseded`; (b) `sources.extracted_text` from `NULL` to a value; (c) `payments.run_id` alone, and only while the old run's status is `failed` (the Phase 3 crash replay). `payments.pay` re-points only in case (c) and writes a `payment_repointed` audit event `{from_run_id, to_run_id}`. A replay whose paying run is not `failed` (for example a second concurrent approve) gets the existing receipt with no update. Cost: `payments` is not strictly append-only, and the original paying run is recorded only in the audit trail. The alternative was a separate `payment_runs` link table, which would have meant rewriting Phase 3's `_receipt` and `check_identity` queries.
3. **`findings` and `decisions` are also immutable** (no code updates them). This is how "re-validated from scratch rather than having findings removed" is enforced. Cost: none today. A future feature that edits a finding needs a new row instead.
4. **Schema upgrade from the immediately previous version only.** `SCHEMA_VERSION = <current + 1>`. When this phase is executed, the current value is whatever `main` holds after Phase 3 (schema 5, `runs.mode_switch_of`) and the P5 API stream (`idempotency_keys`) have merged, and the executor fills the number in. `init_schema` applies one in-place migration from `SCHEMA_VERSION - 1`: `ALTER TABLE … ADD COLUMN`, the `origin` rewrite, then the triggers. Older versions are refused as today. Cost: one migration path to maintain. Anything older still needs a fresh database.
5. **Version origins are `source` | `correction`.** The migration rewrites the existing `extracted` rows to `source` before the triggers exist. `version_status` is `current` (not superseded) or `superseded`. The single pointer is `invoices.current_version`. A correction and a corrected submission both mark the version they replace as `superseded`. Conflicting plain uploads are not superseded. Cost: one data rewrite in the migration.
6. **P4-01 carry-over: `record_version` keeps both behaviours, now pinned by tests.** A semantic-hash match returns the existing version: the hash covers all payable content, and the run keeps its own `source_id`. A repeat of an older version does not move `current_version`, because "current" moves only on a new version or a review action. Corrections bypass the hash match (Decision 7). Cost: none for payment safety. A UI showing "the file of version N" shows the first file.
7. **Corrections always insert a new version** (`ledger.record_correction_version`), even when the semantic hash equals an existing one. This matters because `invoice_date`, `subtotal`, `tax` and `shipping` are not in the hash. Cost: two versions may share a hash. Lookups take the first match, which is safe because neither can be paid without its own approval.
8. **The evidence rule binds the field to its location.** The cited location must resolve in the stored source text (`evidence.locate`). It must not be a recorded evidence location of a different field (header `field_evidence` or another line's evidence; JSON paths match by prefix). And the located text must support the new value under the per-type rule in Task 2. This is what stops "correcting" a wrong total to the subtotal's figure by citing the subtotal line. `NormalizedInvoice` gains `field_evidence` (copied from the draft) so the rule can be checked after ingestion. Cost: a value that is legitimately printed on another field's line cannot be cited, so the operator must submit a corrected invoice. Versions recorded before this phase have no `field_evidence` and are refused with `evidence_unavailable`.
9. **Source text is persisted for every format.** The ingestion node stores the decoded text it already builds (Phase 3 `source_text`) in `sources.extracted_text` (only when it is `NULL`). Cost: the local database holds each invoice's text (≤ 10 MiB). It is still never logged. Sources processed before this phase cannot be corrected (`source_text_unavailable`).
10. **Corrections may not change identity (P4-03 deferred).** A `vendor` or `invoice_number` correction is accepted only if `normalize.vendor_key` / `invoice_number_key` of the new value equals the current key. Otherwise it is refused with `identity_correction_deferred`. Cost: invoices with a missing vendor or number (pending identity, INV-1009) can be fixed only by a corrected submission once P4-03 ships.
11. **No correction can turn a stated non-USD currency into USD.** `currency` is correctable only when the base version's currency was missing, assumed (`currency_assumed_usd`) or unparseable. Otherwise it is refused with `field_not_correctable` (round 5 #3). Cost: a genuinely misread `€` can only be fixed by a corrected invoice.
12. **Carried findings.** A correction or human-review run starts at `validation`. It carries forward the base run's *ingestion-stage* findings (identity, normalization, extraction, model-assist and risk codes) and drops, for a correction, those whose `field` names a corrected field. Validation, approval and the gate then recompute everything else. The stage of a code comes from explicit sets `codes.VALIDATION_CODES` and `codes.GATE_CODES`. Every other code is ingestion-stage, and a corpus test pins the partition. Cost: a new validation code must be added to the set, and the test catches an omission.
13. **Approve/decline revalidate deterministically but never call a model.** The human-review run reruns the validation node, so an inventory edit since the wait would surface. It then runs `approval.resume`: the waiting run's final recommendation, plus the human review, go into the gate. Cost: a stock change between wait and approval turns an approval into a rejection, which is the safe direction.
14. **Decline is a gate outcome.** When rule 3 applies and the matching human review is `decline`, the gate returns `rejected` with rule `R3_human_declined` and adds the new finding `human_declined` (blocker). A later run of the same version therefore also rejects. Cost: one new finding code and one gate branch.
15. **Run linkage.** New columns `runs.trigger` (`submission` | `correction` | `human_review` | `corrected_submission`, default `submission`) and `runs.review_of` (the run this one continues), plus `corrections.run_id` and `human_reviews.run_id`. A run created by a review action advances `received → extracted` when it is created, with audit event `review_run_created`. The transition table is unchanged. Cost: the stage history of these runs shows `extracted` for a step they did not re-extract. The audit event explains it.
16. **Review runs reuse the base run's mode and `evaluation_date`.** A correction of a live invoice runs live; missing credentials raise `ConfigurationError` before anything is written. Cost: a due-date warning is not refreshed for a late approval. Warnings never change outcomes.
17. **Review-triggered runs count as prior outcomes** in `find_prior_outcome` / `check_identity`, because they are not retries. Re-uploading the original bytes after a correction returns the latest outcome for that source (for example the corrected version's receipt). Cost: the duplicate result points at the correction run rather than the first run.
18. **Phase 3 `retry_run` is extended.** A failed `correction` run is retried on the same version from `validation`, with no file needed (`path` may be `None`). Retrying the original source would re-extract version 1. Cost: a signature change (`path: str | Path | None`).
19. **Refusals are exceptions; successes are `ProcessingResult`s.** `review.ReviewRefused(code: ReviewRefusal, message: str, current: AllowedActions | None)` carries the current status, version and allowed actions, so P5 can answer 409/422 with the fresh record. An invalid reason or reviewer raises Pydantic `ValidationError` before any database access. Cost: callers catch two exception types.
20. **Repeated approve on a paid invoice writes nothing.** If the status is `paid_mock` and `expected_version` equals the paid version, `approve` returns the paying run's result (`review.load_result`) with the existing receipt. Any other version gets `stale_version`. Cost: the second click leaves no audit row. P5 idempotency keys cover request-level replay.
21. **Queue scope.** `list_queue` lists invoices whose status is `needs_review` or `awaiting_human_approval`. Rejected invoices are reached from their detail page ("Add corrected invoice"). `needs_review` goes to `correctable_extraction` when every review finding is in `codes.EXTRACTION_REVIEW_CODES` (`ambiguous_normalization`, `unparseable_value`, `ambiguous_date`, `due_date_unresolved`, `duplicate_field`, `malformed_row`, and Phase 3's `model_parser_disagreement`). Otherwise it goes to `unresolved_blocker`. Cost: rejected-but-correctable invoices (missing field, OCR line total) are not in the queue.
22. **Supersede (confirmed, round 5 #5).** `review.submit_corrected_invoice` checks eligibility first: no payment; status `rejected`, `needs_review` or `failed`; no version whose latest business run is `awaiting_human_approval` / `approved` / `paid_mock`. It then calls `service.process_invoice(..., supersede=SupersedeLink(...))`. This skips the byte-level duplicate check (like Phase 3's mode switch), fails the run with `corrected_identity_mismatch` if the parsed identity keys differ from the linked invoice (before `upsert_invoice`), records the version with `supersede=True`, and lets `check_identity` apply only the payment rule. A semantic match with a superseded version yields an ordinary `version_conflict`. Cost: the corrected file must carry the same vendor and number as the invoice it replaces.

## Review Focus

1. **A source error dressed as a correction by citing another field's line.** Correcting `source_error.json`'s total to the subtotal figure while citing `$.subtotal` must be refused (`evidence_location_mismatch`), with no new version. Test in Task 2.
2. **An approval from a stale screen after a correction.** `approve(expected_version=1)` after a correction created version 2 is refused with `stale_version`. A forged `approved` decision for version 1 reaching `payments.pay` is refused with `stale_version` as well. No payment in either case. Test in Task 3.
3. **Repeated, crossed and late clicks.** Approve twice, approve after decline, decline after payment, approve on EUR `needs_review`: each must return the existing receipt or refuse (`action_not_allowed` / `already_paid`). The `payments` row count stays ≤ 1. Test in Task 3.
4. **A corrected file for the wrong invoice, or one already uploaded plainly.** A different identity is refused with `corrected_identity_mismatch`, with no new invoice row. A file first uploaded plainly (`version_conflict`) still supersedes when it is submitted through the corrected path. Test in Task 4.
5. **Correcting a live invoice without credentials.** `ConfigurationError` is raised before any version, correction or run row exists. Test in Task 2.

---

### Task 1 [SDD]: Schema, immutability, version ledger and review contracts (P4-01, carry-overs P4-01, Decision 2)

**Files:**
- Modify: `src/invoice_processing/storage.py`, `src/invoice_processing/ledger.py`, `src/invoice_processing/payments.py` (replay re-point condition only), `src/invoice_processing/codes.py`, `src/invoice_processing/schemas.py`
- Create: `tests/fixtures/review/previous_schema.sql` (a `.dump` of a database built by the pre-Phase-4 code after offline runs of `invoice_1001.txt` and `tests/fixtures/threshold/valid_10000_01.json`, including `PRAGMA user_version`), `tests/test_immutability.py`, `tests/test_migration.py`, `tests/test_review_contracts.py`
- Modify: `tests/test_ledger.py`, `tests/test_storage.py`, `tests/test_codes.py`

**Interfaces — produces:**
- `storage.SCHEMA_VERSION = <current + 1>`. Fresh DDL and migration add: `invoice_versions.version_status TEXT NOT NULL DEFAULT 'current' CHECK (version_status IN ('current','superseded'))`; `runs.trigger TEXT NOT NULL DEFAULT 'submission'`; `runs.review_of TEXT REFERENCES runs(run_id)`; `corrections.run_id TEXT REFERENCES runs(run_id)`; `human_reviews.run_id TEXT REFERENCES runs(run_id)`; and the triggers `immutable_<table>_update` / `immutable_<table>_delete` (`CREATE TRIGGER IF NOT EXISTS`, body `SELECT RAISE(ABORT, 'immutable:<table>')`) with the three exceptions of Decision 2.
- `storage.init_schema(conn)`: when `user_version == SCHEMA_VERSION - 1`, one write transaction: ALTERs → `UPDATE invoice_versions SET origin='source' WHERE origin='extracted'` → triggers → `PRAGMA user_version`. Other older versions still raise `SchemaVersionError`.
- `codes.ReviewAction(StrEnum)`: `correct`, `approve`, `decline`, `submit_corrected`.
- `codes.ReviewRefusal(StrEnum)`: `unknown_invoice`, `stale_version`, `action_not_allowed`, `already_paid`, `field_not_correctable`, `identity_correction_deferred`, `invalid_value`, `correction_not_in_source`, `evidence_location_mismatch`, `evidence_unavailable`, `source_text_unavailable`, `corrected_identity_mismatch`.
- `codes.QueueGroup(StrEnum)`: `correctable_extraction`, `awaiting_human_approval`, `unresolved_blocker`.
- `FindingCode.human_declined` (blocker; description "A human reviewer declined this version.").
- `codes.VALIDATION_CODES`, `codes.GATE_CODES = {model_disagreement, non_usd_currency, human_declined}`, `codes.EXTRACTION_REVIEW_CODES` (Decision 21), `codes.INGESTION_CODES = set(FindingCode) - VALIDATION_CODES - GATE_CODES`.
- `schemas`: `ReviewerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]`, `ReviewReason` (same, max 1000). Then:
  - `FieldChange(field: str, new_value: str, evidence_location: str)`. `field` matches `^(vendor|invoice_number|invoice_date|due_date|currency|stated\.(subtotal|tax|shipping|total)|lines\[\d+\]\.(item|quantity|unit_price|line_total))$`; `new_value` 1–200 characters stripped; `evidence_location` 1–200.
  - `CorrectionRequest(invoice_id, expected_version: int ≥ 1, changes: list[FieldChange] 1..10 with unique fields, reason: ReviewReason, reviewer: ReviewerName)`.
  - `Correction(invoice_id, base_version, field, old_value: str | None, new_value, evidence_location, reviewer, reason, created_at: datetime, resulting_version)`.
  - `HumanReview` gains `created_at: datetime | None = None`; `reviewer` / `reason` become `ReviewerName` / `ReviewReason`.
  - `AllowedActions(invoice_id, status: InvoiceStatus, current_version: int | None, allowed: list[ReviewAction], refused: dict[ReviewAction, ReviewRefusal])`.
  - `QueueItem(invoice_id, vendor_name, invoice_number, total: DecimalStr | None, currency, status, current_version, reason_codes: list[FindingCode], actions: AllowedActions)`; `ReviewQueue(groups: dict[QueueGroup, list[QueueItem]])` (every group key always present).
  - `SupersedeLink(invoice_id, reviewer: ReviewerName, reason: ReviewReason)`.
  - `ApprovalDecision.human_review: HumanReview | None = None`; `ProcessingResult.version: int | None = None` (filled by `service._result` from state); `NormalizedInvoice.field_evidence: dict[str, list[EvidenceRef]] = {}` (populated in Task 2).
- `ledger`:
  - `start_run(conn, mode, source_id, evaluation_date, retry_of=None, mode_switch_of=None, trigger="submission", review_of=None) -> str`.
  - `append_audit_event(..., actor: str | None = None)` writes `audit_events.actor`.
  - `record_version(conn, invoice_id, invoice, source_id, origin="source", supersede=False) -> tuple[str, int]`. With `supersede=True` and no hash match: insert, set every other `current` version of the invoice to `superseded`, move `current_version`.
  - `record_correction_version(conn, invoice_id, invoice, source_id, base_version: int) -> tuple[str, int]` (always inserts `origin='correction'`, `parent_version=base_version`, version = max + 1; supersedes the base; moves `current_version`).
  - `get_invoice(conn, invoice_id) -> InvoiceRow` (frozen dataclass: `invoice_id`, `vendor_key`, `invoice_number_key`, `status: InvoiceStatus`, `current_version: int | None`).
  - `get_version(conn, invoice_id, version) -> VersionRow` (`version_id`, `version`, `parent_version`, `origin`, `version_status`, `source_id`, `invoice: NormalizedInvoice`).
  - `latest_outcome_run(conn, version_id) -> RunRow | None` (latest run on that version whose status is in `BUSINESS_OUTCOMES`; `RunRow` has `run_id`, `status`, `mode`, `evaluation_date`, `trigger`, `review_of`).
  - `get_decision(conn, run_id) -> ApprovalDecision | None`; `get_source(conn, source_id) -> SourceDocument`.
  - `record_correction(conn, correction: Correction, run_id) -> int`; `record_human_review(conn, review: HumanReview, run_id) -> int`.
  - `carried_findings(conn, run_id, exclude_fields: frozenset[str] = frozenset()) -> list[ValidationFinding]` (that run's recorded findings whose code is in `INGESTION_CODES` and whose `field` is not excluded).
- `payments.pay`: the same-version replay branch updates `run_id` only when the paying run's status is `failed` (Decision 2), with event `payment_repointed`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_immutability.py — db after offline 1001 + a correction row and a human review row inserted via ledger
@pytest.mark.parametrize("table", ["sources", "invoice_versions", "corrections", "human_reviews",
                                   "payments", "audit_events", "findings", "decisions"])
def test_delete_rejected(conn_with_history, table):
    with pytest.raises(sqlite3.DatabaseError, match=f"immutable:{table}"):
        with storage.write_transaction(conn_with_history):
            conn_with_history.execute(f"DELETE FROM {table}")

# UPDATE of one ordinary column per table raises the same way, for example
# invoice_versions.payload_json, payments.amount, sources.original_name, human_reviews.reason
def test_version_status_current_to_superseded_allowed(...): ...    # succeeds
def test_version_status_superseded_to_current_rejected(...): ...  # raises immutable:invoice_versions
def test_extracted_text_fill_allowed_once(...): ...               # NULL -> text ok; text -> other raises
def test_payment_repoint_only_from_failed_run(...):
    # status of paying run 'paid_mock' -> UPDATE payments SET run_id raises; after marking it failed -> ok
def test_concurrent_style_second_pay_same_version_returns_receipt_without_update(...):
    # pay() twice for the same approved version from two approved runs: created False, payments.run_id unchanged
```

```python
# tests/test_migration.py
def test_previous_version_db_upgrades_without_data_loss(tmp_path):
    conn = load_dump(tmp_path, "tests/fixtures/review/previous_schema.sql")
    before = {t: count(conn, t) for t in TABLES}
    storage.init_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
    assert {t: count(conn, t) for t in TABLES} == before
    assert {r[0] for r in conn.execute("SELECT DISTINCT origin FROM invoice_versions")} == {"source"}
    assert {r[0] for r in conn.execute("SELECT DISTINCT version_status FROM invoice_versions")} == {"current"}
    with pytest.raises(sqlite3.DatabaseError, match="immutable:payments"):
        with storage.write_transaction(conn): conn.execute("DELETE FROM payments")
def test_two_versions_back_still_refused(...): ...   # user_version = SCHEMA_VERSION - 2 -> SchemaVersionError
```

```python
# tests/test_review_contracts.py
@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_blank_reason_rejected(reason):
    with pytest.raises(ValidationError): CorrectionRequest(invoice_id="inv-1", expected_version=1,
        changes=[FieldChange(field="stated.total", new_value="1.00", evidence_location="line:1")],
        reason=reason, reviewer="Ana")
# also: blank reviewer; 101-char reviewer; field "line_items[2].unit_price" and "stated.amount" rejected;
# "lines[2].unit_price" accepted; duplicate fields in one request rejected; 0 or 11 changes rejected;
# HumanReview(reason="  ") rejected.

# tests/test_ledger.py (add)
def test_correction_versions_increment_and_link_parent(conn): # v1 -> v2 -> v3, parent 1 and 2,
    # origin 'correction', v1 and v2 'superseded', invoices.current_version == 3
def test_correction_version_inserted_even_with_equal_semantic_hash(conn): ...
def test_record_version_hash_match_returns_first_payload_and_keeps_current(conn): ...  # carry-over pinned
def test_record_version_supersede_marks_others(conn): ...
def test_carried_findings_only_ingestion_codes_and_excludes_fields(conn): ...
def test_audit_actor_recorded(conn): ...

# tests/test_codes.py (add)
def test_code_stage_sets_partition_all_codes(): ...   # disjoint; union == set(FindingCode)
def test_human_declined_is_blocker(): ...
```

- [ ] **Step 2: Run them to see them fail.** Run `uv run pytest tests/test_immutability.py tests/test_migration.py tests/test_review_contracts.py tests/test_ledger.py tests/test_codes.py -q`. Expected: FAIL (missing names, no triggers).
- [ ] **Step 3: Build `previous_schema.sql`.** Check out `main` into a scratchpad worktree, run the two offline invoices into a fresh database, then `sqlite3 db .dump > tests/fixtures/review/previous_schema.sql` and add `PRAGMA user_version=<N>;`. `load_dump` in the test runs `executescript`.
- [ ] **Step 4: Implement** the DDL, migration and triggers, the codes, the contracts and the ledger functions with the signatures above, plus the `pay` re-point condition. Each trigger's `WHEN` clause compares every column with `IS NOT`, so `NULL` values compare correctly.
- [ ] **Step 5: Run the tests.** Run `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`. Expected: all pass, including `tests/test_acceptance.py` unchanged.
- [ ] **Step 6: Commit.** `git commit -m "feat: immutable review history, version ledger, review contracts and schema upgrade"`

---

### Task 2 [SDD]: Evidence verifier, corrections and revalidation runner (P4-02, Decisions 7–12, 16–18)

**Files:**
- Create: `src/invoice_processing/evidence.py`, `src/invoice_processing/review.py`, `tests/fixtures/review/extraction_mistake.txt`, `tests/fixtures/review/ocr_ambiguous.txt`, `tests/fixtures/review/source_error.json`, `tests/review_helpers.py`, `tests/test_evidence.py`, `tests/test_corrections.py`
- Modify: `src/invoice_processing/tools.py` (import `evidence.locate` instead of its private `_locate` and helpers), `src/invoice_processing/normalize.py` (copy `draft.field_evidence` into `NormalizedInvoice.field_evidence`), `src/invoice_processing/agents/ingestion.py` (persist `source_text`), `src/invoice_processing/agents/state.py` (state keys `review_of: str`, `trigger: str`), `src/invoice_processing/service.py`, `tests/test_codes.py` (corpus stage-partition test)

**Interfaces:**
- Consumes: Task 1 ledger, codes and contracts; Phase 3 `reasoning.get_provider`, `ModelError`, `ProcessingResult.recoverable`, `service.retry_run`.
- Produces:
  - `evidence.locate(text: str, location: str) -> str | None` (moved verbatim from `tools._locate`: `line:N`, `page:P,line:N`, `row:N`, `$…` JSON path, `/…` XML path).
  - `evidence.claimed_by_other(field: str, location: str, invoice: NormalizedInvoice) -> bool` (Decision 8; `lines[i].*` owns `lines[i].evidence`; a header field owns `field_evidence[<key>]` where the key is the path without `stated.`; JSON/XML paths match exactly or as a prefix followed by `.`, `[` or `/`).
  - `evidence.supports(field: str, value: str, text: str) -> bool`. The text is first passed through `normalize.fix_ocr_digits` (falling back to the original when nothing changes). Then, by field kind:
    - **money** (`stated.*`, `unit_price`, `line_total`): the value is parsed with `normalize.parse_amount` and quantized to 0.01. It is supported when some token matching `\d(?:[\d.,]|(?<=\d) (?=\d))*` has the same digit string. A token whose last `.`/`,` is not followed by exactly two digits counts as whole units, so `"00"` is appended.
    - **quantity**: a positive integer equal to some `\d+` token.
    - **dates**: an ISO value equal to `dates.parse_date` of some 1–3 consecutive whitespace tokens.
    - **currency**: the ISO code as a word (case-insensitive) or its symbol (`$` USD, `€` EUR, `£` GBP).
    - **text** (`vendor`, `invoice_number`, `item`): the value is a substring of the text after case-folding and removing all whitespace from both.
  - `review.submit_correction(request: CorrectionRequest, *, db_path, events=None, provider=None) -> ProcessingResult`. Order, all inside one `write_transaction` after the provider is resolved (`provider or get_provider(base_run.mode)`, so a `ConfigurationError` comes first):
    1. `unknown_invoice`.
    2. `already_paid` if a payment exists.
    3. `stale_version` if `expected_version != current_version`.
    4. `action_not_allowed` unless `ReviewAction.correct in allowed_actions(...).allowed`.
    5. For each change: `field_not_correctable` (index out of range, or Decision 11) → `invalid_value` (type parse) → `identity_correction_deferred` (Decision 10) → `source_text_unavailable` → `evidence_unavailable` (empty `field_evidence` and no line evidence) → `evidence_location_mismatch` (`locate` is `None` or `claimed_by_other`) → `correction_not_in_source` (not `supports`).
    6. Only after every change passes (all-or-nothing): apply the changes to a copy of the base payload (`computed=None`), appending a `NormalizationEvent(field, raw_value=old, normalized_value=new, evidence=[EvidenceRef(source_id, location, snippet=located[:200])], provenance="review:correction")`.
    7. `record_correction_version`, then `start_run(trigger="correction", review_of=base_run.run_id, mode=base_run.mode, evaluation_date=base_run.evaluation_date)`, then `attach_run`, then `record_correction` per change, then `record_findings(carried_findings(base_run, exclude_fields=...))`, then `update_run_status(extracted)`.
    8. Audit events `correction_applied` (fields, versions) and `approvals_invalidated` (`{superseded_version, decision_run_ids, human_review_ids}`), both with `actor=reviewer`; `set_invoice_status(processing)`. Commit.
    9. `return service.run_existing_version(run_id, ...)`.

    The refusal message for `correction_not_in_source` is exactly "This value is not what the invoice says. Submit a corrected invoice from the vendor." For `evidence_location_mismatch` it is "The cited location is not where the invoice states this field."
  - `review.allowed_actions(invoice_id, *, db_path) -> AllowedActions` and the internal `review._allowed(conn, invoice_id) -> AllowedActions`, using this table:

    | status | allowed | refused |
    | --- | --- | --- |
    | `awaiting_human_approval` | approve, decline, correct | submit_corrected: action_not_allowed |
    | `needs_review`, `rejected` | correct, submit_corrected | approve, decline: action_not_allowed |
    | `failed` | submit_corrected | correct, approve, decline: action_not_allowed |
    | `paid_mock` | — | all: already_paid |
    | `processing` / other | — | all: action_not_allowed |

    `correct` moves to refused (`source_text_unavailable`) when the current version's source has no text, and `submit_corrected` is refused unless Decision 22's eligibility holds.
  - `review.ReviewRefused(Exception)` with `.code`, `.message`, `.current`.
  - `service.run_existing_version(run_id, *, db_path, events=None, provider=None, approval: Literal["agent", "human"] = "agent") -> ProcessingResult`. It loads the run, version, source, carried findings and `source_text` from the ledger, builds `InvoiceState`, invokes `build_graph(deps, start="validation", approval=approval)`, then applies the same finishing logic as `process_invoice`, factored into `service._finish(conn, deps, state) -> ProcessingResult`. `approval="human"` is added in Task 3; until then it raises `NotImplementedError`.
  - `service.retry_run(run_id, path: str | Path | None, db_path, evaluation_date, events=None, provider=None)`. A failed run with `trigger == "correction"` is retried from `validation` on the same version via a new run (`retry_of`, same trigger and `review_of`, carried findings). `path` is ignored there. Other runs behave as in Phase 3.
  - `tests/review_helpers.py`: `EVAL = date(2026, 1, 31)`; `seeded_db(tmp_path) -> Path`; `process(path, db, mode=offline, provider=None) -> ProcessingResult`; `payment_count(db, invoice_id) -> int`; `change(field, value, loc) -> FieldChange`; `correct(db, result, *changes, reason="Misread total", reviewer="Ana", provider=None) -> ProcessingResult`.
- Fixtures:
  - `extraction_mistake.txt`: the `invoice_1001.txt` layout with vendor `Correction Test Co`, number `CT-3001`, date `2026-01-20`, due `2026-03-01`, one item `WidgetA qty: 7 unit price: $500.00`, `Subtotal: $3,500.00`, `Tax (0%): $0.00`, `Total Amount: $3.500,00`. Expected first outcome `needs_review` (`unparseable_value` on the total).
  - `ocr_ambiguous.txt`: a P2-03 column table `Item  Qty  Unit Price  Amount` with one row `WidgetA  7  $450.00  $3,5O0.00`, subtotal and total `$3,150.00`. Expected `needs_review` (`ambiguous_normalization` on `lines[0].line_total`).
  - `source_error.json`: the `invoice_1013.json` shape with vendor `Source Error Supply`, number `SE-4001`, date `2026-01-20`, due `2026-03-01`, lines WidgetA 10 × 250.00 and WidgetB 5 × 500.00, `subtotal` 5000.00, `tax_rate` 0, `tax_amount` 0.00, `total` 5050.00, `USD`. Expected `rejected` (`total_mismatch`).

  If the parsers read a fixture differently, adjust only the fixture's layout until its first outcome is as stated. Never adjust the parser.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evidence.py
@pytest.mark.parametrize("field,value,text,ok", [
    ("stated.total", "3500.00", "Total Amount: $3.500,00", True),
    ("stated.total", "22512.80", '"total": 22562.80', False),
    ("stated.total", "5000.00", "Total: $5,000", True),
    ("lines[0].line_total", "3500.00", "WidgetA  7  $450.00  $3,5O0.00", True),
    ("lines[0].line_total", "350.00", "WidgetA  7  $450.00  $3,5O0.00", False),
    ("lines[0].unit_price", "12.50", "qty 1250", False),
    ("lines[0].quantity", "7", "WidgetA qty: 7 unit price: $500.00", True),
    ("due_date", "2026-03-31", "Remittance note: due date extended to 2026-03-31", True),
    ("currency", "USD", "Total: €4,125.00", False),
    ("lines[0].item", "WidgetA", "  Widget A    qty: 10", True),
])
def test_supports(field, value, text, ok): assert evidence.supports(field, value, text) is ok
def test_locate_matches_phase3_tool_excerpts(): ...   # same results as get_source_excerpt for INV-1001 line:9, 1013 $.total
def test_claimed_by_other_subtotal_line_for_total(): ...

# tests/test_corrections.py (offline, seeded tmp db, EVAL)
def test_extraction_mistake_corrected_then_paid(tmp_path):
    db = seeded_db(tmp_path); r1 = process(REVIEW / "extraction_mistake.txt", db)
    assert r1.status == "needs_review" and r1.version == 1
    r2 = correct(db, r1, change("stated.total", "3500.00", "line:13"))   # the Total Amount line
    assert r2.status == "paid_mock" and r2.version == 2 and r2.receipt.amount == Decimal("3500.00")
    assert "unparseable_value" not in codes(r2.findings) and payment_count(db, r1.invoice_id) == 1
    assert r2.decision.initial_recommendation is not None             # approval/critique reran
def test_ocr_ambiguous_correction_is_revalidated_not_cleared(tmp_path):
    # correct lines[0].line_total -> 3500.00 citing the row line: supported; r2.status == "rejected",
    # "line_total_mismatch" in codes(r2.findings); correcting to "3150.00" -> ReviewRefused correction_not_in_source
def test_inv_1013_total_correction_refused(tmp_path):
    # stated.total 22512.80 citing $.total -> code correction_not_in_source, message exact;
    # SELECT COUNT(*) FROM invoice_versions unchanged; no corrections row; no new run
def test_source_error_cannot_cite_subtotal(tmp_path):         # Review Focus 1
    # source_error.json: stated.total 5000.00 citing $.subtotal -> evidence_location_mismatch; citing $.total -> correction_not_in_source
def test_stale_expected_version_writes_nothing(tmp_path):    # after one correction, a second with expected_version=1
    # -> stale_version; e.current.current_version == 2; row counts of versions/corrections/runs unchanged
def test_source_bytes_and_v1_payload_unchanged(tmp_path):    # sha256 of file, sources row, v1 payload_json identical
def test_all_or_nothing_multi_field(tmp_path):              # one good + one unsupported change -> refused, no version
def test_paid_invoice_correction_refused(tmp_path):         # INV-1001 paid -> already_paid
def test_identity_change_refused(tmp_path):                 # invoice_number -> "CT-9999" citing line:4 -> identity_correction_deferred
def test_explicit_eur_currency_not_correctable(tmp_path):   # INV-1014 currency -> USD -> field_not_correctable
def test_correction_audit_and_links(tmp_path):              # corrections.run_id == r2.run_id; runs.trigger 'correction';
    # runs.review_of == r1.run_id; audit actor 'Ana'; events correction_applied, approvals_invalidated
def test_live_correction_without_credentials_writes_nothing(tmp_path, monkeypatch):  # Review Focus 5
    # base processed live with a fake provider; correction with provider=None and no XAI_* env -> ConfigurationError;
    # versions/corrections/runs counts unchanged
def test_failed_live_correction_retried_on_same_version(tmp_path):
    # live base (fake: no assist proposals, approve, agree); correction with fake Raise(UNAVAILABLE) x2 -> failed,
    # recoverable, no payment; service.retry_run(r2.run_id, None, ...) with a working fake -> paid_mock, version 2,
    # retry_of == r2.run_id, payment_count == 1

# tests/test_codes.py (add)
def test_corpus_findings_respect_stage_sets(tmp_path):
    # for every file in data/invoices: findings recorded by the validation node ⊆ VALIDATION_CODES,
    # by the gate ⊆ GATE_CODES (read via spies on validation.run / policy.evaluate)
```

- [ ] **Step 2: Run them to see them fail.** Run `uv run pytest tests/test_evidence.py tests/test_corrections.py tests/test_codes.py -q`. Expected: FAIL (no `evidence` / `review` modules).
- [ ] **Step 3: Implement** `evidence.py`, the `tools.py` import switch (Phase 3 `tests/test_tools.py` must stay green), `field_evidence` copying, `source_text` persistence, `review.submit_correction` / `allowed_actions` / `ReviewRefused`, `service.run_existing_version` / `_finish`, and the `retry_run` extension, with the signatures above.
- [ ] **Step 4: Run the tests.** Run `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`. Expected: all pass, acceptance unchanged.
- [ ] **Step 5: Commit.** `git commit -m "feat: evidence-backed corrections with versioned revalidation"`

---

### Task 3 [SDD]: Human approve/decline, gate decline rule and stale-version payment guard (P4-04, carry-over P4-04, Decisions 13, 14, 20)

**Files:**
- Modify: `src/invoice_processing/policy.py`, `src/invoice_processing/payments.py`, `src/invoice_processing/agents/approval.py`, `src/invoice_processing/workflow.py`, `src/invoice_processing/reasoning/base.py`, `src/invoice_processing/review.py`, `src/invoice_processing/service.py`
- Create: `tests/fixtures/review/correction_after_recommendation.txt`, `tests/test_human_approval.py`
- Modify: `tests/test_policy.py`, `tests/test_payments.py`, `tests/test_agents.py`

**Interfaces:**
- Consumes: Task 1 contracts and ledger; Task 2 `review._allowed`, `ReviewRefused`, `service.run_existing_version`, `tests/review_helpers.py`; Phase 3 threshold fixtures `tests/fixtures/threshold/valid_10000_00.json` and `valid_10000_01.json`.
- Produces:
  - `policy.evaluate(invoice, findings, recommendation, human_review=None, *, version=None, invoice_id=None) -> GateResult`. The match also requires `human_review.invoice_id == invoice_id`. Under rule 3, a matching `decline` gives `rejected`, `rule_ids=["R3_human_declined"]` and an added `human_declined` finding. `approval.run` passes `invoice_id`.
  - `payments.pay`: after the existing checks, it raises `PaymentNotAuthorized("stale_version")` when the version's number ≠ `invoices.current_version` or its `version_status == 'superseded'`.
  - `reasoning.base.NoModelProvider(mode: ExecutionMode)`: `provider = "none"`, `model = "none"`, `prompt_version = None`. All four methods raise `AssertionError("human-review runs make no model calls")`.
  - `agents.approval.resume(state, deps) -> dict`. It reads the decision of `state["review_of"]` (the waiting run) and takes `final = revised_recommendation or initial_recommendation`, then the latest human review for the version (`ledger.get_human_review`). It then calls `policy.evaluate(..., version=state["version"], invoice_id=state["invoice_id"])`, records the gate findings and an `ApprovalDecision` (initial, critique summary and revised copied from the waiting decision; `final_decision` = gate outcome; `mode` = run mode; provider and model copied; `human_review` set), and moves the status. Events: `human_review_applied` (actor = reviewer), `decision`.
  - `workflow.build_graph(deps, start="ingestion", approval: Literal["agent", "human"] = "agent")`. With `"human"`, the `approval` node is `approval.resume`, and the same `route_after_approval` edges lead to payment or outcome.
  - `review.approve(invoice_id, expected_version, reviewer, reason, *, db_path, events=None) -> ProcessingResult` and `review.decline(...)` (same signature). The `HumanReview` contract is built first, so a blank reason raises `ValidationError` before any database access. Then, in one `write_transaction`:
    - `unknown_invoice`;
    - paid → (approve and `expected_version` == paid version: return `load_result(paying_run)`, with no writes) | (decline, or another version: `already_paid` / `stale_version`);
    - `stale_version`;
    - `action_not_allowed` unless the action is in `_allowed(...).allowed`;
    - then `start_run(trigger="human_review", review_of=<latest outcome run of the current version>, mode=<its mode>, evaluation_date=<its date>)`, `attach_run`, `record_human_review(..., run_id)`, carried findings (no exclusions), `update_run_status(extracted)`.

    Commit, then `run_existing_version(run_id, approval="human", provider=NoModelProvider(mode))`.
  - `review.load_result(run_id, *, db_path) -> ProcessingResult` (from the ledger: status, invoice, version, mode, findings, decision, receipt via `payments.run_id`).
- Fixture `correction_after_recommendation.txt` (layout of `invoice_1001.txt`): vendor `Review Path Supply`, number `RP-2001`, date `2026-01-20`, `Due Date: 2026-03-15`, items `WidgetA qty: 10 unit price: $1,000.00` and `WidgetB qty: 4 unit price: $500.00`, `Subtotal: $12,000.00`, `Tax (0%): $0.00`, `Total Amount: $12,000.00`, and a last line `Remittance note: due date extended to 2026-03-31 by agreement`. Expected first outcome `awaiting_human_approval` (only info and warning findings).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_human_approval.py (offline, seeded tmp db, EVAL)
def test_10000_00_auto_pays(tmp_path):
    r = process(THRESHOLD / "valid_10000_00.json", seeded_db(tmp_path))
    assert r.status == "paid_mock" and r.receipt.amount == Decimal("10000.00")
def test_10000_01_waits_then_approve_pays_once(tmp_path):
    db = seeded_db(tmp_path); r1 = process(THRESHOLD / "valid_10000_01.json", db)
    assert r1.status == "awaiting_human_approval" and r1.receipt is None and payment_count(db, r1.invoice_id) == 0
    r2 = review.approve(r1.invoice_id, 1, "Ana", "Checked against PO", db_path=db)
    assert r2.status == "paid_mock" and r2.receipt.amount == Decimal("10000.01")
    assert r2.decision.reasons == ["R4_human_approved"] and r2.decision.human_review.reviewer == "Ana"
    r3 = review.approve(r1.invoice_id, 1, "Ana", "again", db_path=db)
    assert r3.receipt.receipt_id == r2.receipt.receipt_id and payment_count(db, r1.invoice_id) == 1
def test_decline_rejects_and_later_approve_refused(tmp_path):
    # decline -> status "rejected", "human_declined" in codes, decision.reasons == ["R3_human_declined"],
    # decision.human_review.reason == the reason; approve afterwards -> ReviewRefused action_not_allowed; 0 payments
def test_approve_stale_after_correction(tmp_path):            # Review Focus 2
    # correction_after_recommendation.txt -> awaiting v1; correct due_date "2026-03-31" citing the note line ->
    # r2.status "awaiting_human_approval", r2.version == 2, critique recorded; approve(expected_version=1) -> stale_version,
    # 0 payments; approve(expected_version=2) -> paid_mock 12000.00
def test_pay_refuses_superseded_version_even_with_forged_approval(tmp_path):
    # after the correction above: record_decision(approved) for the v1 run + record_human_review(approve, version 1);
    # payments.pay(conn, inv, v1_version_id, v1_run) -> PaymentNotAuthorized("stale_version")
def test_pay_without_human_review_over_threshold_raises(tmp_path):
    # 10000_01 waiting run; insert approved decision for a new run on v1 -> pay -> "human_approval_required"
def test_model_disagreement_wait_uses_same_actions(tmp_path):
    # offline provider stub recommending reject on INV-1001 -> awaiting with model_disagreement; approve -> paid_mock 5000.00
def test_crossed_and_late_actions(tmp_path):                  # Review Focus 3
    # approve on INV-1014 (needs_review) -> action_not_allowed; decline on a paid invoice -> already_paid;
    # approve twice after payment -> same receipt; payments rows <= 1 throughout
def test_approval_never_calls_a_model(tmp_path):              # live waiting run; approve with no XAI env -> paid; fake call log empty
def test_approval_revalidates(tmp_path):                      # UPDATE inventory stock of WidgetA to 0 after the wait ->
    # approve -> "rejected" (zero_stock / quantity_exceeds_stock), no payment

# tests/test_policy.py (add)
def test_human_review_for_other_invoice_does_not_count(): ...   # invoice_id mismatch -> awaiting_human_approval
def test_matching_decline_rejects(): ...                         # R3_human_declined + human_declined finding
# tests/test_agents.py (add, carry-over P4-04)
def test_approval_node_applies_existing_human_approval(conn): ...  # approve row for v1 exists -> R4_human_approved
```

- [ ] **Step 2: Run them to see them fail.** Run `uv run pytest tests/test_human_approval.py tests/test_policy.py tests/test_payments.py tests/test_agents.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the gate change, the pay guard, `NoModelProvider`, `approval.resume`, the `build_graph` option, `run_existing_version(approval="human")`, `review.approve` / `decline` / `load_result`.
- [ ] **Step 4: Run the tests.** Run `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`. Expected: all pass, acceptance unchanged.
- [ ] **Step 5: Commit.** `git commit -m "feat: version-bound human approve/decline with stale-version payment guard"`

---

### Task 4 [SDD]: Review queue and corrected-invoice submissions (P4-05, Decisions 21–22)

**Files:**
- Modify: `src/invoice_processing/review.py`, `src/invoice_processing/service.py`, `src/invoice_processing/agents/ingestion.py`, `src/invoice_processing/agents/state.py` (state key `supersede: SupersedeLink | None`), `src/invoice_processing/ledger.py` (`check_identity(..., superseding: bool = False)`)
- Create: `tests/fixtures/review/inv_1013_corrected.json`, `tests/test_review_queue.py`, `tests/test_corrected_submission.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `review.list_queue(*, db_path) -> ReviewQueue` (Decision 21; `reason_codes` = review and blocker codes of the latest outcome run of the current version, sorted; items ordered by `invoices.updated_at`).
  - `review.submit_corrected_invoice(invoice_id, path, reason, reviewer, *, db_path, evaluation_date, mode: ExecutionMode | None = None, events=None, provider=None, limits=DEFAULT_LIMITS) -> ProcessingResult`. `SupersedeLink` is validated first. Refusals: `unknown_invoice`, `already_paid`, `action_not_allowed` (eligibility, Decision 22). `mode` defaults to the latest run's mode. The function delegates to `service.process_invoice(path, mode, db_path, evaluation_date, events, limits, provider=provider, supersede=link)`.
  - `service.process_invoice(..., supersede: SupersedeLink | None = None)`: with a link, the run gets `trigger="corrected_submission"`, skips `find_prior_outcome`, and emits a `corrected_submission` audit event (actor = reviewer, reason).
  - Ingestion node with `state["supersede"]`:
    - parsed keys ≠ the linked invoice's keys → `status=failed`, `error_code="corrected_identity_mismatch"`, no `upsert_invoice`;
    - else `record_version(..., origin="source", supersede=True)`, and if the returned version is `superseded` → `version_conflict` finding;
    - `check_identity(..., superseding=True)` applies only the payment rule (`revision_after_payment`) and never returns `duplicate` or `version_conflict` from history.
- Fixture `inv_1013_corrected.json`: identity identical to `invoice_1013.json` (vendor `Atlas Industrial Supply`, number `INV-1013`), lines WidgetA 15 × 1,000.00, WidgetB 10 × 500.00, GadgetX 1 × 1,040.00 (subtotal 21,040.00), `tax_rate` 0.07, `tax_amount` 1,472.80, `total` 22,512.80, `USD`, due `2026-03-24`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_queue.py (one persistent seeded db with 1001, 1003, 1014, extraction_mistake, valid_10000_01)
def test_queue_groups(db):
    q = review.list_queue(db_path=db)
    assert set(q.groups) == set(QueueGroup)
    eur = item(q, QueueGroup.unresolved_blocker, "INV-1014")
    assert ReviewAction.approve not in eur.actions.allowed and eur.actions.refused[ReviewAction.approve] == "action_not_allowed"
    hv = item(q, QueueGroup.awaiting_human_approval, "TH-10000-01")
    assert {ReviewAction.approve, ReviewAction.decline} <= set(hv.actions.allowed)
    assert item(q, QueueGroup.correctable_extraction, "CT-3001").reason_codes == ["unparseable_value"]
    assert not any(i.invoice_number in {"INV-1001", "INV-1003"} for g in q.groups.values() for i in g)
def test_allowed_actions_matches_service_refusals(db): ...
    # for each queued invoice and each ReviewAction refused by allowed_actions, calling the action raises that same code

# tests/test_corrected_submission.py
def test_corrected_1013_supersedes(tmp_path):
    db = seeded_db(tmp_path); r1 = process(DATA / "invoice_1013.json", db)        # rejected
    r2 = review.submit_corrected_invoice(r1.invoice_id, REVIEW / "inv_1013_corrected.json",
                                         "Vendor reissued invoice", "Ana", db_path=db, evaluation_date=EVAL)
    assert r2.invoice_id == r1.invoice_id and r2.version == 2 and r2.status == "awaiting_human_approval"
    assert version_status(db, r1.invoice_id, 1) == "superseded" and origin(db, r1.invoice_id, 2) == "source"
    assert review.approve(r1.invoice_id, 2, "Ana", "ok", db_path=db).status == "paid_mock"
def test_plain_upload_is_version_conflict(tmp_path):
    # fresh db: 1013 json then inv_1013_corrected.json via process() -> needs_review with version_conflict
def test_plain_upload_first_then_corrected_path_still_supersedes(tmp_path): ...   # Review Focus 4
def test_wrong_identity_refused(tmp_path):            # link 1013, submit source_error.json -> failed corrected_identity_mismatch;
    # no invoices row for SE-4001
def test_not_eligible(tmp_path):
    # linked to paid INV-1001 -> already_paid; to waiting TH-10000-01 -> action_not_allowed; blank reason -> ValidationError
def test_superseded_history_kept(tmp_path):            # v1 run, findings and decision rows still readable and unchanged
```

- [ ] **Step 2: Run them to see them fail.** Run `uv run pytest tests/test_review_queue.py tests/test_corrected_submission.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the queue, the corrected-submission service path, the ingestion supersede branch and `check_identity(superseding=True)`.
- [ ] **Step 4: Run the tests.** Run `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`. Expected: all pass, acceptance unchanged.
- [ ] **Step 5: Commit.** `git commit -m "feat: review queue, allowed actions and corrected-invoice supersede"`

---

### Task 5 [light]: Review acceptance sequences and Phase 4 docs (P4-07 without thread tests)

**Files:**
- Create: `tests/test_review_acceptance.py`
- Modify: `docs/PRD.md` (Phase 4 exit boxes with test ids), `docs/tickets/P4-01`, `P4-02`, `P4-04`, `P4-05`, `P4-07` (status `done`; P4-04 / P4-07 note "thread tests deferred"), `docs/tickets/README.md` (Phase 4 rows, struck P4-01 / P4-04 carry-over rows, the "Open decision in P4-05" line → decided round 5 #5), `docs/limitations.md` (row 9 → implemented; new note for Decisions 8, 10 and 11), `docs/development.md` (a "Review workflow" section with the Python calls `review.submit_correction`, `approve`, `decline`, `submit_corrected_invoice`, `list_queue`)

**Interfaces — consumes:** everything above. No production code changes. A failing scenario is fixed in its owning module and recorded in the commit message.

- [ ] **Step 1: Write the acceptance tests.** Each test ends with `assert payment_count(db, invoice_id) <= 1`.
  - `valid_10000_00.json` → `paid_mock`, no human action. `valid_10000_01.json` → waits → approve → `paid_mock`.
  - `extraction_mistake.txt` → `needs_review` → correction → `paid_mock`. `source_error.json` → `rejected`; correction refused (`correction_not_in_source`).
  - `correction_after_recommendation.txt`: v1 decision run ids are listed in `approvals_invalidated`; v2 has its own recommendation and critique events; a stale approve gives `stale_version`; a repeated approve returns the same receipt.
  - **Restart:** `subprocess.run([sys.executable, "main.py", "--invoice_path=tests/fixtures/threshold/valid_10000_01.json", "--db", db, ...])` → exit 0 and `awaiting_human_approval`. Then `review.approve` in this process (a fresh connection) → `paid_mock`, one payment.
  - **Live failure during re-review:** use the Task 2 scenario through the public calls → `failed`, `recoverable`, unpaid. `retry_run` → paid.
  - **Property:** for every `FindingCode` whose `DEFAULT_SEVERITY` is `blocker` or `review`, `policy.evaluate(<clean 10000.01 invoice>, [finding(code)], Recommendation.approve, <matching approve review>, version=1, invoice_id=...)` has `outcome != approved`. For every such code recorded on a queued invoice, `approve` raises `action_not_allowed`.
  - **Offline guard:** the whole module runs under the autouse `no_network` guard; `tests/test_acceptance.py` is untouched.
- [ ] **Step 2: Run the tests.** Run `uv run pytest tests/test_review_acceptance.py -q`, fix anything they reveal in the owning module, then `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`. Expected: all pass.
- [ ] **Step 3: Update the docs** as listed in Files. The PRD boxes "10,000.00 auto-pays; 10,000.01 waits", "Human approval cannot override any hard blocker" and "Stale approval after a correction cannot reach payment" are ticked with their test ids.
- [ ] **Step 4: Commit.** `git commit -m "test: Phase 4 review acceptance sequences; close P4-01/02/04/05/07"`

---

## Self-review

- **Spec coverage.**
  - P4-01: contracts, versions and status (Task 1); triggers including the re-point (Decision 2); reason validation; upgrade test.
  - P4-02: all four acceptance criteria, multi-field all-or-nothing, original mode, auto-pay when clean (Task 2).
  - P4-04: every acceptance criterion except the thread test (Task 3). Model-disagreement wait is covered, and so is "no transaction open while waiting" (by construction: Steps commit before `run_existing_version`).
  - P4-05: all four acceptance criteria and `allowed_actions` (Tasks 2 and 4).
  - P4-07: every row of the scenario table except the threads (Task 5).
  - PRD exit criteria: Tasks 3 and 5.
  - Round 5 #3 (EUR): Decision 11, the gate R2 order and the Task 3 crossed-actions test.
  - Round 5 #5 (supersede): Decision 22 and Task 4.
  - P4-01 / P4-04 carry-overs: Decision 6 with the Task 1 tests, and Task 3's `invoice_id` match plus the approval-node test.
  - Deferred P4-03 / P4-06 are stated as out of scope, and Decision 10 refuses identity changes instead of half-supporting them.
- **Type consistency.**
  - `ReviewRefused.current: AllowedActions`.
  - `run_existing_version(..., approval="agent" | "human")` matches `build_graph(..., approval=)`.
  - `start_run(..., trigger=, review_of=)` is used identically in Tasks 2–4.
  - `ProcessingResult.version` is set in Task 1 and asserted in Tasks 2–5.
  - Field paths use `lines[N]` everywhere, not the ticket's `line_items[N]`.
- **Gaps fixed while writing.**
  - Retry of a correction run would have re-extracted version 1 (Decision 18).
  - Phase 3's unconditional re-point would have collided with the payments trigger (Decision 2).
  - Hash-equal corrections (Decision 7).
  - The subtotal-line disguise (Decision 8).
- **Proportion.** Code appears only for test assertions and the evidence rules. Bodies are left to the implementer.
