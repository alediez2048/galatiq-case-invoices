# Robustness campaign, offline part (P6-01)

Date: 2026-11-01. Branch `p6-robustness`. Tests only; nothing under `src/` or `main.py` changed.
Run: `uv run pytest` gave 725 passed, 1 xfailed in about 46 s (whole suite); the new files alone are 130 passed, 1 xfailed in about 30 s (the 7 subprocess tests dominate, 15-25 s depending on machine load).

## What ran

| File | Tests | Covers |
| --- | --- | --- |
| `tests/test_robustness_corpus.py` | 8 | All 20 samples through one ledger, forward (alphabetical) then reverse order, each on a fresh DB; whole-corpus reprocess |
| `tests/test_robustness_injection.py` | 24 (1 xfail until Phase 3 Task 6, now passing) | Exception at intake, each of 5 parsers (generic exception and `ExtractionError`), normalization, ingestion agent, validation, approval, gate, decision record, payment before commit, gateway decline, failure between gateway and commit, payment after commit, late invoice-status failure |
| `tests/test_robustness_malformed.py` | 74 | 37 malformed inputs, each checked through the service and through the in-process CLI |
| `tests/test_robustness_replay.py` | 7 | Repeated `python main.py` subprocess runs with `INVOICE_NETWORK_GUARD=1`, `--db` in tmp |
| `tests/test_robustness_threshold.py` | 18 | 8 fixtures in `tests/fixtures/robustness/`, each checked for outcome and for rerun payment count |

Shared helpers: `tests/robustness.py`. Every scenario uses a fresh temporary DB; the repo `inventory.db` is never touched; the network guard stays active.

## Results

### 1. Whole corpus, one ledger, both orders
- Exactly 7 payments in both orders (identities 1001, 1004, 1006, 1010, 1011, 1012, 1015). Gateway calls, `payments` rows, distinct idempotency keys and paid runs are all equal to 7. No run `failed`.
- "Identical final outcome per identity" is defined as: same set of identities, same invoice status per identity, same payment count per identity, same paid amount per identity. Allowed to differ with order, and asserted exactly:
  - Format twins 1011 and 1012 (txt/pdf): whichever file is processed first is `paid_mock`, the second is `duplicate` with the same receipt id and amount (3000.00, 9975.00). Forward order pays the `.pdf` (alphabetical), reverse pays the `.txt`.
  - 1013 (json/pdf): the identity is `rejected` either way; the first file is `rejected`, the second a `duplicate` with no receipt.
  - INV-1004: the first version processed is the one paid. Forward pays the original (1890.00) and routes the revision to `needs_review` (`revision_after_payment`); reverse pays the revision (5940.00) and routes the original to `needs_review`. The amount paid therefore depends on arrival order by design (first payment wins; a later version never pays).
- Reprocessing the whole corpus on the finished DB yields only `duplicate` results and no gateway call.

### 2. Error injection
- Every injected exception before payment ends as `failed` / `unexpected_error` with zero payments and zero gateway calls, and a clean rerun then pays exactly once (all but the EUR 1014 file, which never auto-pays).
- A parser raising `ExtractionError` keeps its own code and creates no invoice row.
- Intake: an `IntakeError` creates no run (existing contract). An unexpected non-`IntakeError` exception from `read_source` propagates out of `process_invoice` with no run and no payment (see limitations).
- Payment before commit: the transaction rolls back (no row); the rerun pays once. A gateway returning `{"status": "error"}` gives `failed` with `payment_not_authorized:mock_payment_failed`.
- Gateway call succeeded but the write fails before commit: no row; the replay calls the gateway again with the same idempotency key (`invoice:<id>`) and records one payment. This is the documented at-least-once contract: a real gateway must dedupe on the key.
- Payment after commit: run ends `failed`, the payment row exists. The rerun reveals the existing receipt (`created=False`) with no new gateway call; further reruns add no payment.
- Exception in `set_invoice_status` after payment keeps the run `paid_mock` with `errors == ["unexpected_error"]`.

### 3. Malformed input (37 cases x service + CLI)
Truncated files of each format; binary junk with each valid extension; NUL-containing junk; deeply nested JSON (100k arrays, 50k objects) and XML (100k elements); 2 MB single lines in txt/json/csv/xml; XML entity expansion; Latin-1, UTF-16 and mixed valid/invalid UTF-8 in each text format; wrong-content files (PDF bytes as `.txt`, XML as `.json`, text as `.pdf`); empty and whitespace-only files.
- Intake codes: `format_mismatch` (NUL bytes, UTF-16, wrong content), `empty_file`. Run failure codes: `txt_decode_error`, `json_invalid` (includes recursion depth), `csv_decode_error` (includes field over the 128 KiB csv limit), `xml_invalid`, `xml_forbidden_construct`, `pdf_corrupt`. Parseable-but-empty cases (truncated txt/csv, huge single-line txt/json/xml, deeply nested XML) end `rejected` with at least one blocker.
- No payment in any case; the CLI exits 2 (intake), 1 (failed) or 0 (rejected) and never prints `Traceback`. A UTF-8 BOM is accepted (control). Malformed runs do not prevent a later valid invoice paying once on the same DB.

### 4. Payment replay by CLI subprocess
Four repeated runs: 1 `paid_mock` then 3 `duplicate`, one receipt id, one "Paying" stderr line, 4 run rows, 1 payment row. Renamed copy and other-format twin are duplicates; revision after payment is `needs_review` then `duplicate`, only 1890.00 paid; unpayable outcomes (rejected, EUR, 1013) replayed twice create no payment; a failed run (exit 1) followed by a good file pays once; separate DBs each pay once.

### 5. Threshold boundaries
Offline expectation holds: total <= 10,000.00 and clean is `paid_mock`; > 10,000.00 is `awaiting_human_approval` with `R3_high_value`, no receipt, no payment, and reruns never pay. Cases: 9,999.99; 10,000.00; 10,000.01; subtotal 9,999.99 plus tax 0.01 (= 10,000.00, paid) and plus 0.02 (= 10,000.01, held); subtotal 9,500 plus tax 400 plus shipping 100.00 (paid) and 100.01 (held); subtotal exactly 10,000.00 plus shipping 0.01 (held).

## Bugs found

1. **Duplicate of a post-commit-recovered run carries no receipt** (`tests/test_robustness_injection.py::test_duplicate_after_post_commit_recovery_still_shows_receipt`; was xfail strict). **Fixed in Phase 3 Task 6 (P3-08):** when `payments.pay` replays a payment whose paying run is `failed`, it re-points `payments.run_id` to the replaying run and records a `payment_run_repointed` audit event, so the third run finds the receipt; the test now passes.
   Inputs: `invoice_1001.txt`; first run pays then fails after commit (`update_run_status(paid_mock)` raises); second run of the same file reveals the payment (`paid_mock`, `created=False`, receipt returned); third run of the same file.
   Expected: `duplicate` with `receipt` equal to the existing receipt, as in the normal duplicate case. Actual: `duplicate` with `receipt=None`.
   Cause (from reading `ledger._prior` / `_receipt`): the receipt is looked up by the prior run's `run_id`, but the payment row is stamped with the first (failed) run's id, while the second run is the one found as prior outcome. No money impact: the payment count stays 1 and no gateway call is made. Only the displayed receipt is wrong. Suggested fix: look the receipt up by `invoice_id` (one payment per identity) when the prior run is `paid_mock`.

## Known limitations

- An unexpected (non-`IntakeError`) exception from `intake.read_source` propagates out of `process_invoice` and, in the CLI, which calls `read_source` before the service, would surface as a traceback. In practice `read_source` wraps `OSError`, so this was injected, not reproduced.
- Single-file post-commit and between-gateway-and-commit failures rely on the gateway deduplicating by idempotency key (`invoice:<id>`); the mock gateway has no dedupe, and the tests assert only that the key is stable.
- The corpus replay test is order-dependent at the end of its module (the whole-corpus reprocess reuses the forward DB).
- Time-bounded checks are coarse: the 2 MB single lines and 100k-deep nesting complete in well under a second each; no explicit timing assertion.

## Not covered yet

- Generated-variation fuzzing (shuffled lines, whitespace/case noise, renamed files, label spellings, quantity bumps): deferred by the 2026-11-01 cut line.
- Live (Grok) mode: model disagreement paths under real output, live error injection, live threshold fixtures (Phase 3 owns `tests/fixtures/threshold/`), and the `--mode offline` never imports the xAI SDK check.
- API retries with and without idempotency keys, concurrent approvals, process kill between gate and payment (needs the backend and review flow; Phase 4).
- Human-review path: approval of held high-value invoices (threshold above 10,000.00 with a matching human approval pays), review CLI, stale-version approvals.
- Concurrency / thread tests (parallel `process_invoice` on the same DB).
- UI / end-to-end Playwright flows.
