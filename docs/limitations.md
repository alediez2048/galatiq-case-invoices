# Limitations and open assumptions

What this prototype assumes where a question is unresolved, why, and what follows from it. Each item names the working assumption; none is an evaluator-confirmed interpretation. Resolved items live in [decisions](decisions.md). Tracking: [P6-05](tickets/P6-05-open-question-resolution.md).

<a id="l-offline-vs-llm"></a>
## 1. Offline simulator plus live integration versus the brief (row 1)

- **Decided 2026-11-01** ([decisions round 5, item 1](decisions.md#d-dual-mode)). **Interpretation:** the brief asks for LLM reasoning and also forbids external API dependencies at runtime. We treat an explicitly selected `offline` mode (local parsers, deterministic validation, a labeled simulated reasoning adapter, no network) plus a separately selected `live` mode (Grok through `xai_sdk`) as satisfying both. See [constraints](contraints.md#primary-ambiguity-llm-integration-versus-offline-execution).
- **Why:** the two requirements cannot both hold for a single run, so each is met in its own mode.
- **Consequence:** if the evaluator requires real local inference with no network, the offline mode does not meet that; it is a scripted simulator, not a model. Tests use a scripted fake client for the model, not a real one.

<a id="l-live-credentials"></a>
## 2. Grok credentials, model and live-testing budget (row 2)

- **Assumption:** the user will supply an xAI key later (decided 2026-11-01, [decisions](decisions.md#d-speedups)). Tickets P3-01 to P3-09 are built and tested against a scripted fake client; only the live smoke test P3-10 needs the key. The model name and spend limit are not yet confirmed.
- **Consequence:** until then, live behavior has not been exercised against the real provider. Per-invoice model-call budgets are enforced in code but the cost of a full corpus run is unmeasured.

<a id="l-deadline"></a>
## 3. Deadline and target evaluator machine (row 3)

- **Assumption:** no deadline is known. Work follows the tickets-index cut line (core ships; identity corrections, review CLI, accessibility audits, fuzzing, audit export and thread-concurrency tests only if time remains). The evaluator is assumed to have a recent Python and to allow dependency installation over the internet.
- **Consequence:** deferred items may not ship; the prototype is verified on the developer's macOS machine only.

<a id="l-eur"></a>
## 4. EUR settlement (row 4)

- **Decided 2026-11-01** ([decisions round 5, item 3](decisions.md#d-eur)): review-only. Explicit EUR is preserved, never converted, and routed to `needs_review`; settlement is USD-only. INV-1014 (EUR 4,125) ends `needs_review` with `unsupported_currency` and `non_usd_currency` and no receipt (`tests/test_acceptance.py`). A missing currency is treated as USD with a recorded `currency_assumed_usd` finding.
- **Consequence:** a EUR invoice can never be paid by this prototype, even by a human, since no exchange-rate source or EUR settlement exists.

<a id="l-pdf"></a>
## 5. PDF extraction versus generator source (row 5)

Resolved: see [decisions](decisions.md#d-pdf). Residual limit: the three committed PDFs are single-page text PDFs; scanned or image PDFs have no OCR path.

<a id="l-revisions"></a>
## 6. Revision handling and inventory semantics (row 6)

- **Decided 2026-11-01** ([decisions round 5, item 4](decisions.md#d-revisions-inventory)). **Revisions:** a revision of an already-paid invoice is not paid again; it goes to `needs_review` with `revision_after_payment` (INV-1004 revised, `tests/test_acceptance.py`). Changed content under an existing unpaid identity yields `version_conflict`. Duplicates across formats are detected by semantic identity (INV-1013 PDF is a `duplicate` of the JSON).
- **Assumption (inventory):** quantities are positive integers checked against current stock per item; lines for the same item are aggregated (INV-1013 aggregates 22/18/9). Paying an invoice does not decrement stock and nothing is reserved (no inventory update exists in `src`), so two payable invoices can each fit the same stock.
- **Consequence:** an evaluator who expects revisions to supersede and re-pay, or stock to be reserved, will see different behavior.

<a id="l-cli-mode"></a>
## 7. Default CLI mode

Resolved: `offline` ([decisions](decisions.md#d-cli-mode)). Consequence to know: a bare CLI run never contacts a model; live needs `--mode live`.

<a id="l-inv1012"></a>
## 8. INV-1012 auto-pay

Resolved: pays as `paid_mock` ([decisions](decisions.md#d-inv1012)). Residual limit: its OCR-style fixes (`2O26`, `3,500.O0`, spaced item names) are applied automatically on rule-backed evidence with no human look, which is a risk tolerance the user accepted.

<a id="l-supersede"></a>
## 9. Corrected submissions superseding unpaid versions (row 9)

- **Decided 2026-11-01** ([decisions round 5, item 5](decisions.md#d-supersede)); **implemented** in P4-05 (`review.submit_corrected_invoice`, `tests/test_corrected_submission.py`): a corrected invoice supersedes prior versions only when none is paid, approved or awaiting human approval, and only when submitted through the corrected-invoice action with an explicit link and reason. A plain upload with the same identity still gets `version_conflict`. Eligibility is checked when the action is accepted and again when the new version is written; a version held in between fails the run with `supersede_not_allowed`, which cannot be retried.
- **Consequence:** the corrected file must carry the same vendor and invoice number (otherwise `corrected_identity_mismatch`), and a version waiting for approval must be declined before it can be superseded. Rejected invoices are not in the review queue; they are reached from their own record.

<a id="l-corrections"></a>
## 9a. What a correction cannot fix (Phase 4 decisions 8, 10 and 11)

- **The evidence must sit where the field is stated.** A correction cites a location in the stored source text. It must use the location scheme the parser records for that format and must not be another field's recorded location, so a wrong total cannot be "corrected" to the subtotal's figure by citing the subtotal line. A value that is legitimately printed only on another field's line cannot be cited; the operator submits a corrected invoice instead. Invoices processed before Phase 4 have no stored text or field evidence and cannot be corrected (`source_text_unavailable`, `evidence_unavailable`).
- **Identity is not correctable** (P4-03 deferred). A `vendor` or `invoice_number` correction is accepted only when its normalized key is unchanged; otherwise `identity_correction_deferred`. An invoice with a missing vendor or number (INV-1009) can be fixed only by a corrected submission once P4-03 ships.
- **A stated non-USD currency cannot become USD.** `currency` is correctable only when it was missing, assumed USD or unparseable (`field_not_correctable` otherwise), so a genuinely misread `€` also needs a corrected invoice.

<a id="l-readme"></a>
## 10. README layout (row 10)

- **Decided 2026-11-01** ([decisions round 5, item 6](decisions.md#d-readme)): solution section on top with the original assignment text preserved below. Decided in P6-04 once the user answers.
- **Consequence:** purely presentational; the assignment text is not altered either way.

## Other known limits

- Local single operator, serialized processing, no authentication; reviewer identity is recorded for audit only ([constraints](contraints.md)).
- Payment is a mock; idempotency here does not imply exactly-once for a real bank API.
- INV-1007's stated total is 110.00 short of subtotal plus tax ([decisions](decisions.md#d-inv1007)); the prototype reports the discrepancy and rejects, it does not correct the source.
- Corrections (P4-02) carry the base run's ingestion-stage findings forward and drop those naming a corrected field. Findings with no `field` (extraction issues, identity findings) are always carried, which is the safe direction. The normalization warnings `due_before_invoice_date` and `terms_inconsistent` are dropped when a date is corrected and are not recomputed. Warnings never change an outcome.
- A correction, approve or decline commits its new run (and, for a correction, its new version) before the run executes. If the process stops in between, the invoice stays `processing` with a run in `extracted`. A concurrent `process_invoice` startup sweep can also mark such a committed run `interrupted` before it starts. Both cases are recovered with `retry_run(run_id, None)` or `main.py --retry RUN_ID`, without a file; an approve/decline retry calls no model and needs no credentials.
- If the process dies after a review run's payment commits but before the run finishes, the invoice can stay `processing` while a payment exists. `allowed_actions` still answers `already_paid`, and a repeated approve returns the paying run's recorded result (which may still show the unfinished run). Until the run is retried, a re-upload of the original bytes can report the earlier waiting outcome without the receipt. `retry_run(run_id, None)` finishes the run, re-points the payment to the retry and sets the invoice `paid_mock`; it never pays twice, and a later re-upload then returns the retry with its receipt.
- An invoice can show `paid_mock` with a newer `current_version`: a revised upload creates version 2 (`version_conflict`), and a crash replay of version 1 then pays it. The payment always sets the invoice status, so the record says paid while pointing at the unpaid revision. One payment still exists, for the version that was approved.
- A live corrected submission runs model-assisted extraction before the second eligibility check at the version write. If a version became held in the meantime, the run fails `supersede_not_allowed` after spending those model calls.
- `payments.pay` trusts the run's stored `approved` decision: it re-checks the version (current, not superseded), USD, the total, the matching human approval above USD 10,000 or after a model disagreement, and one payment per invoice, but it does not re-read blocker or review findings. Only a forged `decisions` row, not any review action, could reach it with a blocker; the gate is the one place that judges findings.
