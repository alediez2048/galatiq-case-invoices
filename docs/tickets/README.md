# Tickets

Work items derived from the [PRD](../PRD.md). One file per ticket, named `P<phase>-<number>-<slug>.md`. Requirement IDs (A01, P02, …) refer to [requirements.md](../requirements.md).

Status values: `todo`, `in progress`, `blocked`, `done`. Update the status line in the ticket file and in the index below together. Each ticket link is tagged (complete) when its status is `done` and (pending) otherwise.

## Phase 0 — Foundations

Goal: a scaffolded repository with contracts and storage in place. Exit criteria: `pip install` and the seed script work from a clean clone; unit tests cover arithmetic, aggregation, and seed idempotence.

| Ticket | Title | Depends on | Status |
| --- | --- | --- | --- |
| [P0-01](P0-01-project-scaffolding.md) (complete) | Project scaffolding and tooling | — | done |
| [P0-02](P0-02-money-and-currency.md) (complete) | Money and currency primitives | P0-01 | done |
| [P0-03](P0-03-data-contracts.md) (complete) | Core Pydantic data contracts | P0-02 | done |
| [P0-04](P0-04-sqlite-schema.md) (complete) | SQLite schema and storage module | P0-01 | done |
| [P0-05](P0-05-inventory-seed.md) (complete) | Idempotent inventory seed | P0-04 | done |
| [P0-06](P0-06-required-field-checks.md) (complete) | Required-field and value-sign checks | P0-03 | done |
| [P0-07](P0-07-arithmetic-reconciliation.md) (complete) | Arithmetic reconciliation | P0-02, P0-03 | done |
| [P0-08](P0-08-aggregation-and-inventory-check.md) (complete) | Item aggregation and inventory comparison | P0-03, P0-05 | done |

Suggested order: P0-01 → P0-02 and P0-04 in parallel → P0-03 and P0-05 → P0-06, P0-07, P0-08.

Phase 0 is done when every ticket above is `done` and the phase exit criteria are verified from a fresh clone.

## Phase 1 — Walking skeleton (offline, one invoice)

Goal: INV-1001 TXT flows through the CLI to a persisted mock receipt in offline mode. Exit criteria: `paid_mock` with a USD 5,000.00 receipt; rerunning does not pay twice; offline mode makes no network calls.

| Ticket | Title | Depends on | Status |
| --- | --- | --- | --- |
| [P1-01](P1-01-source-intake-and-txt-extraction.md) (complete) | Source intake and clean TXT extraction | P0-03 | done |
| [P1-02](P1-02-ledger-writes.md) (complete) | Ledger writes and audit events | P0-03, P0-04 | done |
| [P1-03](P1-03-reasoning-interface-and-offline-simulator.md) (complete) | Reasoning interface and offline simulator | P0-03 | done |
| [P1-04](P1-04-eligibility-policy-gate.md) (complete) | Deterministic eligibility policy gate | P0-02, P0-03 | done |
| [P1-05](P1-05-guarded-mock-payment-service.md) (complete) | Guarded, idempotent mock payment service | P0-04, P1-02, P1-04 | done |
| [P1-06](P1-06-agent-nodes.md) (complete) | Ingestion, validation, approval, and payment agent nodes | P1-01, P1-03, P1-04, P1-05, P0-06–P0-08 | done |
| [P1-07](P1-07-workflow-and-processing-service.md) (complete) | LangGraph workflow and shared processing service | P1-02, P1-06 | done |
| [P1-08](P1-08-structured-logging-and-results.md) (complete) | Structured logging and result output | P0-01, P0-03 | done |
| [P1-09](P1-09-cli-entry-point.md) (complete) | CLI entry point | P1-07, P1-08 | done |
| [P1-10](P1-10-phase-1-end-to-end-tests.md) (complete) | Phase 1 end-to-end and offline-network tests | P1-09 | done |

Suggested order: P1-01, P1-02, P1-03, P1-04, P1-08 in parallel → P1-05 → P1-06 → P1-07 → P1-09 → P1-10.

Resolved 2026-11-01 (P1-09): the default mode when `--mode` is omitted is `offline`, clearly labeled.

Pulled forward from Phase 2: the recorded USD assumption for invoices without a stated currency (P1-01), because INV-1001 states none and would otherwise be blocked.

## Phase 2 — Full corpus and data integrity

Goal: every supplied fixture produces its expected outcome in offline mode. Exit criteria: all 20 files have asserted outcomes; INV-1013 aggregates 22/18/9 and reports the USD 50.00 discrepancy; alternate formats and revisions yield at most one payment per identity; INV-1014 stays EUR and unpaid.

| Ticket | Title | Depends on | Status |
| --- | --- | --- | --- |
| [P2-01](P2-01-input-limits-and-unsupported-documents.md) (complete) | Input limits and unsupported documents | P1-01 | done |
| [P2-02](P2-02-txt-labeled-layouts.md) (complete) | TXT extraction: labeled layouts, label typos, email bodies | P1-01 | done |
| [P2-03](P2-03-txt-table-layouts.md) (complete) | TXT extraction: column tables and footer totals | P2-02 | done |
| [P2-04](P2-04-json-parser.md) (complete) | JSON parser | P1-01 | done |
| [P2-05](P2-05-csv-parsers.md) (complete) | CSV parsers (field/value and row-table layouts) | P1-01 | done |
| [P2-06](P2-06-xml-parser.md) (complete) | Hardened XML parser | P1-01 | done |
| [P2-07](P2-07-pdf-text-extraction.md) (complete) | PDF text extraction | P2-01, P2-03 | done |
| [P2-08](P2-08-normalization-rules.md) (complete) | Evidence-backed normalization: items, OCR artifacts, identity | P2-02, P2-03 | done |
| [P2-09](P2-09-dates-currency-and-terms.md) (complete) | Dates, currency, and payment terms | P2-08 | done |
| [P2-10](P2-10-duplicates-formats-and-revisions.md) (complete) | Duplicates, alternate formats, and revisions | P1-02, P2-04, P2-07, P2-08, P2-09 | done |
| [P2-11](P2-11-fixture-acceptance-suite.md) (complete) | Fixture acceptance suite | P2-01 – P2-10 | done |

Suggested order: P2-01, P2-02, P2-04, P2-05, P2-06 in parallel → P2-03 → P2-07 and P2-08 → P2-09 → P2-10 → P2-11.

Resolved 2026-11-01 (P2-11): INV-1012 (all corrections rule-backed, USD 9,975.00) auto-pays as `paid_mock`.

Refines Phase 1: P2-10 narrows the P1-02 semantic hash to payable content only, because 1011 PDF omits the subtotal/tax lines its TXT twin states.

## Phase 3 — Live Grok reasoning

Goal: the primary demo runs on real Grok with tool use, structured outputs, and observable self-correction. Exit criteria: explicitly invoked live smoke test passes; controlled tests cover malformed output, budget exhaustion, timeout, and provider failure without payment; payment safety holds regardless of model wording.

Prerequisite: xAI credentials, a confirmed model, and a live-testing budget. Only P3-10 needs them; P3-01 – P3-09 are built and tested against a scripted fake client (complete). P3-10's harness (`tests/live/test_live_smoke.py`) is in place; the run itself waits for the user's xAI key.

| Ticket | Title | Depends on | Status |
| --- | --- | --- | --- |
| [P3-01](P3-01-live-mode-configuration.md) (complete) | Live mode configuration and credentials | P1-03, P1-09 | done |
| [P3-02](P3-02-xai-reasoning-adapter.md) (complete) | xAI reasoning adapter | P1-03, P3-01 | done |
| [P3-03](P3-03-tool-registry-and-dispatcher.md) (complete) | Whitelisted tool registry and dispatcher | P0-08, P1-02, P1-06 | done |
| [P3-04](P3-04-model-call-budget.md) (complete) | Bounded agent loops and per-invoice model budget | P1-07, P3-02, P3-03 | done |
| [P3-05](P3-05-extraction-assist-and-repair.md) (complete) | Model-assisted extraction with one repair retry | P2-08, P3-02 – P3-04 | done |
| [P3-06](P3-06-live-approval-and-critique.md) (complete) | Live approval recommendation and critique loop | P1-04, P3-02 – P3-04 | done |
| [P3-07](P3-07-untrusted-input-safeguards.md) (complete) | Untrusted invoice text and prompt-injection safeguards | P3-05, P3-06 | done |
| [P3-08](P3-08-live-failure-and-explicit-retry.md) (complete) | Live failure handling and explicit retry | P1-07, P3-02, P3-04 | done |
| [P3-09](P3-09-scripted-provider-contract-tests.md) (complete) | Scripted fake provider and live-path contract tests | P3-02 – P3-08 | done |
| [P3-10](P3-10-live-smoke-test-and-verification.md) (pending) | Live Grok smoke test and verification record | P3-01 – P3-09 | blocked |

Suggested order: P3-01 and P3-03 in parallel → P3-02 → P3-04 → P3-05, P3-06, P3-08 in parallel → P3-07 → P3-09 → P3-10.

Pulled forward from Phase 4: the valid USD 10,000.00 / 10,000.01 threshold fixtures (P3-06), needed to show high-value critique.

SDK details in P3-02 were read from xAI docs on 2026-11-01 and must be re-verified against the installed version.

## Phase 4 — Human review workflow (service layer)

Goal: corrections and high-value approvals work end to end through the shared service, before any UI. Exit criteria: 10,000.00 auto-pays and 10,000.01 waits for explicit approval; human approval cannot override any hard blocker; stale approval after a correction cannot reach payment.

| Ticket | Title | Depends on | Status |
| --- | --- | --- | --- |
| [P4-01](P4-01-versioning-and-review-contracts.md) (complete) | Invoice versioning and review contracts | P0-04, P2-10 | done |
| [P4-02](P4-02-evidence-backed-corrections.md) (complete) | Evidence-backed correction and revalidation | P1-07, P3-05, P4-01 | done |
| [P4-03](P4-03-identity-corrections-and-duplicate-safety.md) (pending) | Identity corrections and duplicate safety | P2-10, P4-02 | todo |
| [P4-04](P4-04-human-approval-for-high-value.md) (complete) | Human approval for high-value invoices (thread tests deferred) | P1-05, P3-06, P4-01 | done |
| [P4-05](P4-05-review-queue-and-corrected-submissions.md) (complete) | Review queue and corrected-invoice submissions | P4-02, P4-04 | done |
| [P4-06](P4-06-review-cli.md) (pending) | Review CLI | P4-02 – P4-05 | todo |
| [P4-07](P4-07-review-acceptance-tests.md) (complete) | Review workflow acceptance fixtures and tests (thread tests deferred) | P4-01 – P4-06 | done |

Suggested order: P4-01 → P4-02 and P4-04 in parallel → P4-03 and P4-05 → P4-06 → P4-07.

Resolved 2026-11-01 ([decisions round 5, item 5](../decisions.md#d-supersede)), built in P4-05: a corrected vendor invoice supersedes unpaid prior versions only through the explicit corrected-invoice action with a reason, and only when no version is paid, approved or awaiting human approval; a plain upload stays `version_conflict`.

P4-03 (identity corrections) and P4-06 (review CLI) are deferred by the cut line: a `vendor` / `invoice_number` correction that changes the identity is refused with `identity_correction_deferred`, and the review actions are Python calls ([development](../development.md#review-workflow)). P4-07 was built against them as they are.

## Phase 5 — API and operator UI

Goal: the approved mockup becomes a working React + TypeScript app backed by FastAPI. Exit criteria: every state visually checked at desktop and narrow widths with real data; browser coverage for correction, approval, and stale/repeated actions; frontend typecheck and build pass with local-only assets.

| Ticket | Title | Depends on | Status |
| --- | --- | --- | --- |
| [P5-01](P5-01-fastapi-app-skeleton.md) (pending) | FastAPI application skeleton | P1-07, P2-11, P3-08 (retry only) | todo |
| [P5-02](P5-02-submission-and-progress-endpoints.md) (pending) | Submission and processing-progress endpoints | P2-01, P5-01 | todo |
| [P5-03](P5-03-read-and-dashboard-endpoints.md) (pending) | Invoice, detail, and dashboard read endpoints | P5-01 | todo |
| [P5-04](P5-04-review-action-endpoints.md) (pending) | Review action endpoints | P4-02 – P4-05, P5-01 | todo |
| [P5-05](P5-05-frontend-scaffold-and-app-frame.md) (pending) | Frontend scaffold, design tokens, and app frame | P5-01 | todo |
| [P5-06](P5-06-overview-and-invoice-list.md) (pending) | Empty workspace, overview, and invoice list | P5-03, P5-05 | todo |
| [P5-07](P5-07-add-invoice-and-processing.md) (pending) | Add invoice and processing views | P5-02, P5-05 | todo |
| [P5-08](P5-08-invoice-detail-and-states.md) (pending) | Invoice detail and outcome states | P5-03, P5-05 | todo |
| [P5-09](P5-09-needs-review-and-actions.md) (pending) | Needs-review queue, corrections, and approvals UI | P5-04, P5-08 | todo |
| [P5-10](P5-10-accessibility-responsive-and-browser-tests.md) (pending) | Accessibility, responsive layout, and browser test suite | P5-06 – P5-09 | todo |

Suggested order: P5-01 → P5-02, P5-03, P5-05 in parallel → P5-06, P5-07, P5-08 in parallel (these need only Phase 2, so they can run alongside Phases 3–4) → P5-04 and P5-09 after Phase 4 → P5-10.

New tooling proposed (not yet user-confirmed): `openapi-typescript` for the typed client, Playwright and axe for browser and accessibility tests.

## Phase 6 — Hardening and submission

Goal: a reproducible, documented public submission. Exit criteria: clean-install offline run covers every supplied file; live demo verified separately; the public repository URL reproduces the documented results.

| Ticket | Title | Depends on | Status |
| --- | --- | --- | --- |
| [P6-01](P6-01-robustness-test-campaign.md) (pending) | Robustness test campaign | P2-11, P3-09, P4-07, P5-10 | todo |
| [P6-02](P6-02-audit-trail-completeness.md) (pending) | Audit trail completeness and export | P4-07, P5-03 | todo |
| [P6-03](P6-03-demo-setup-and-walkthrough.md) (pending) | Demo setup and evaluator walkthrough | P5-10 (offline half); P3-10 (live half) | todo |
| [P6-04](P6-04-submission-documentation.md) (pending) | Submission documentation and business-impact narrative | P2-11, P6-03 offline half | todo |
| [P6-05](P6-05-open-question-resolution.md) (pending) | Resolve or disclose open questions | — | todo |
| [P6-06](P6-06-release-checks-and-publish.md) (pending) | Release checks and public GitHub submission | P6-01 – P6-05 | todo |

Suggested order: P6-05 can start now → P6-01 and P6-02 in parallel → P6-03 → P6-04 → P6-06.

Open decision in P6-04: README layout (solution section on top with the assignment text preserved below, recommended).

## Cut line (decided 2026-11-01)

If time runs short, **core** ships and **deferred** does not. Core is still a complete, demonstrable product: CLI + corpus + live Grok + corrections and high-value approval + a working UI + a public repo.

| | Tickets |
| --- | --- |
| **Core** | All of P0, P1, P2 · P3-01 – P3-06, P3-09 (P3-10 when credentials exist) · P4-01, P4-02, P4-04, P4-05, P4-07 (without thread tests) · P5-01, P5-02, P5-03, P5-04, P5-05, P5-06, P5-07, P5-08, P5-09 (simplified: approve/decline and one correction form) · P6-03 offline half, P6-04, P6-05, P6-06 |
| **Deferred** | P4-03 (identity corrections) · P4-06 (review CLI) · P5-10 axe and screenshot review (keep the Playwright happy-path tests) · P6-01 generated-variation fuzzing (keep corpus, replay, threshold, error-injection) · P6-02 audit export CLI (keep the completeness test) · thread-concurrency tests in P4-04 |

Deferred tickets stay in the index with their status; their scope is not removed, only sequenced last.

## Plan review (2026-11-01)

An independent review of all 62 tickets produced 24 findings; every fixture value cited in the tickets was verified correct. Fixes applied in place, each marked with the date: run vs invoice status split and a `review` severity (P0-03), arithmetic rule (P0-07), duplicate detection excludes failed/retry/mode-switch runs and always creates a run (P1-07, P2-10, P3-08), gate takes a `human_review` input and model disagreement on a clean invoice waits for a human rather than rejecting (P1-04, P1-05, P3-06, P4-04), provisional identity for invoices without vendor/number (P1-02), budget counts top-level steps only (P3-04), `INVOICE #` pattern and email-header skip (P2-02, P2-03), mutable `version_status` (P4-01, P4-05), corrections allowed on rejected invoices (P4-02, P4-07), UI decoupled from Phase 4 (P5-01), offline/live walkthrough split (P6-03, P6-04), CLI auto-seeds like the API (P1-09), API idempotency table and sample sanitization (P5-01, P5-02).

## All open decisions

Collected in [P6-05](P6-05-open-question-resolution.md): corrected-submission supersede rule (P4-05), README layout (P6-04), plus the constraints document's open questions (offline/LLM interpretation, credentials and budget, deadline, EUR, revision semantics). Resolved 2026-11-01: default CLI mode is `offline` (P1-09); INV-1012 auto-pays (P2-11); model disagreement routes to human approval; scope cut line adopted; provider adapter stays on the official `xai_sdk`.

## Phase 1 carry-overs (recorded 2026-11-01)

Deferred findings from the Phase 1 reviews, each assigned to the ticket that should absorb it.

| Target | Item |
| --- | --- |
| ~~P2-01~~ | ~~`intake.read_source` does not wrap `OSError`.~~ Done (intake.py wraps `OSError`). |
| ~~P2-02~~ | ~~Repeated label silently overwrites.~~ Done (`tests/test_parser_text.py::test_repeated_label_is_duplicate_field_first_wins`). |
| ~~P2-08~~ | ~~Header values cite all draft evidence; `parse_amount` accepts misplaced commas.~~ Done (per-field evidence in normalize.py; `tests/test_normalize.py::test_parse_amount_rejects_misplaced_commas`). |
| ~~P2-10~~ | ~~Revision under a paid identity; `find_prior_outcome` and `mark_interrupted_runs` tests.~~ Done (`revision_after_payment`, `tests/test_ledger.py`). Not done, moved to P4-01 (versioning): `record_version` returns the first source's payload on a semantic-hash match, and a repeat of an older version does not move `current_version`; neither can cause a second payment. |
| ~~P2-11~~ | ~~Repo-db e2e SHA-256; first-run status asserts; `None` total and combined high-value + disagreement gate cases.~~ Done (Task 12). |
| ~~Phase 2 deps~~ | ~~Declare `langsmith>=0.14,<1` in `pyproject.toml`.~~ Done. |
| ~~P3-08~~ | ~~(Phase 2 final review) Retry runs skip the identity check, so a retried revision of a paid invoice ends `failed` (`payment_not_authorized:revision_after_payment`) instead of `needs_review`; after a repaired crash replay the paying `payments.run_id` still points at the failed run, so an exact re-submission returns `duplicate` without a receipt and `check_identity` keeps returning `new` — re-point `payments.run_id` on replay or fall back to the invoice payment. No money moves in either case.~~ Done (retries run the identity check; a replay re-points a failed payer's payment: `tests/test_retry.py`). |
| ~~P3-01 / P3-07~~ | ~~Disable LangSmith tracing in live mode too; redaction misses camelCase names; network guard leaves `connect_ex`/`getaddrinfo` unpatched; exact-threshold critique test; approval-node revision path untested.~~ Done: tracing forced off in both modes (`service.py`, `tests/test_e2e.py`), camelCase redaction (`tests/test_ledger.py`), guard extended (`tests/test_network_guard.py`), `tests/test_live_approval.py` (USD 10,000.00 and 10,000.01 critique, revision path). Not done, moved to P6: declare the reasoning protocol attributes as `ClassVar`. |
| ~~P4-01~~ | ~~`record_version` reuses the first source's payload on a semantic-hash match; a repeat of an older version does not move `current_version` (moved from P2-10; no double-payment risk).~~ Done: both behaviours kept and pinned (`tests/test_ledger.py::test_record_version_hash_match_returns_first_payload_and_keeps_current`, `::test_record_version_does_not_move_current_version_when_paid`). |
| ~~P4-04~~ | ~~Gate's human-review match ignores `invoice_id` (ledger query filters by it and `pay` rechecks — make it explicit); approval-node human-review path untested.~~ Done: `policy.evaluate` takes `invoice_id` (`tests/test_policy.py::test_human_review_for_other_invoice_does_not_count`); approval-node path in `tests/test_human_approval.py::test_10000_01_waits_then_approve_pays_once`. |
| P5 | `mark_interrupted_runs(utcnow())` would fail a concurrent process's live run — add a grace window before FastAPI concurrency; observability: caller `ts=` overrides the timestamp, `write_result` treats a `str` path as a stream, tests leave the events logger configured. |
| P6 | Reasoning protocol attrs (`mode`, `provider`, `model`, prompt versions) as `ClassVar` (moved from P3-01 / P3-07). Payment: reserve-then-execute (pending row) before any real gateway, positive-amount guard, empty vendor name; service exception path drops `invoice_id`/findings/timings and leaves `invoices.status` intermediate; `attach_run`/`set_invoice_status` no-op on unknown ids; CLI tracebacks for unexpected errors (unwritable `--output`); `atomic` join test strength; audit polish (stale status on recommendation/critique events, generic `waiting` event, `error_message` never set, cwd-relative pay-guard test). |
