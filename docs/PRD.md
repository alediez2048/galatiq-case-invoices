# Product requirements document — Invoice Operations

Status: consolidated PRD derived from the existing design documents. It introduces no new decisions; where the sources leave something open, it stays open here. Nothing described below is implemented yet.

Sources: [assignment](../README.md), [requirements](requirements.md), [constraints](contraints.md), [decisions](decisions.md), [system design](systemsdesign.md), [technology stack](techstack.md), [style guide](styleguide.md), [experience mockup](mockup.md). When this PRD and a source disagree, the source wins and this document should be corrected.

## 1. Summary

A local, runnable multi-agent prototype that takes an invoice document from ingestion to a decision: extract fields, validate against SQLite inventory, reason through approval with a critique loop, and either issue a mock payment or record why not. Every decision is explainable from persisted evidence. Real Grok reasoning is the primary demo; an explicitly selected offline simulator provides no-key, no-network reproducibility.

**Tagline:** From invoice to decision. Every check visible.

## 2. Problem

Acme Corp (fictional, PE-backed manufacturer) processes emailed invoices by hand: messy PDFs, manual extraction, validation against an inconsistent inventory system, VP approval by email chain, then payment. The scenario cites $2M/year in losses, a 30% error rate, and five-day delays. These are scenario inputs, not measured outcomes or promised savings.

## 3. Users

| User | Need |
| --- | --- |
| Accounts-payable operator | Submit an invoice, see extracted evidence and findings, get a decision and mock receipt. |
| Reviewer / approver | Correct evidence-backed extraction mistakes; explicitly approve or decline eligible invoices above USD 10,000. |
| Evaluator | Clone the public repo, install, seed, run the CLI and UI, and reproduce every documented outcome. |

## 4. Goals and non-goals

**Goals**

- End-to-end processing of all supplied fixtures with correct, explained outcomes.
- Payment safety that does not depend on model wording: deterministic gates, idempotent mock payments, no duplicates across reruns, formats, revisions, or modes.
- Genuine agentic behavior: distinct agents, tool calls, structured outputs, bounded self-correction and critique, verified against real Grok.
- An operator UI that preserves the approved mockup and makes every check visible.

**Non-goals (MVP)**

- Real bank integration, email intake, cloud hosting, multi-tenant or enterprise auth.
- OCR for image-only PDFs, credit notes, partial payments, fractional units, FX conversion, EUR settlement.
- Three-way matching, vendor authentication, or claims of fraud detection beyond available evidence.
- Distributed queues, vector databases, generalized ERP integrations.

## 5. Core business rules

Full policy: [requirements — business policy](requirements.md#business-policy).

- Quantities are positive integers; totals positive; prices, tax, shipping nonnegative.
- Vendor, invoice identity, due date, currency, total, and complete line items are required for payment. Missing values are never invented.
- Money uses `Decimal`; a discrepancy above one cent blocks payment.
- Quantities aggregate per canonical item before stock checks. Inventory is a fixed snapshot, not decremented.
- **Hard blockers** (non-overridable): unknown item, zero stock, overstock, inconsistent totals, unsupported currency, prior payment.
- Clean eligible USD totals **≤ 10,000.00** may auto-pay. Otherwise-valid totals **> 10,000.00** wait in `awaiting_human_approval` after recommendation and critique.
- Missing currency may use a recorded USD assumption; explicit EUR is preserved and routed to review.
- Past absolute due dates warn; relative dates ("yesterday") remain unresolved.
- Outcomes: `paid_mock`, `rejected`, `needs_review`, `awaiting_human_approval`, `failed`, `duplicate`.

## 6. Solution overview

Architecture detail: [system design](systemsdesign.md).

- **CLI** (`python main.py --invoice_path=...`) and **FastAPI** both call one Python processing service.
- **LangGraph** coordinates four agents: Ingestion → Validation → Approval (with critique) → Payment.
- **Deterministic services** own arithmetic, inventory checks, duplicate detection, and payment eligibility. Model output never authorizes payment on its own.
- **SQLite** (`inventory.db`) holds inventory and the processing ledger: sources, invoices, versions, runs, findings, decisions, corrections, human reviews, payments, audit events.
- **Reasoning adapters**: live xAI/Grok and an offline simulator behind one typed interface. No silent fallback between them.
- **React + TypeScript UI** implements the approved mockup over the FastAPI backend.

## 7. Delivery phases

Each phase leaves the system in a working, demonstrable state and builds on the previous one. Order follows the [system design delivery order](systemsdesign.md#verification-and-delivery-order): CLI flow first, then fixture coverage and reliability, then UI. Requirement IDs refer to [requirements.md](requirements.md).

### Phase 0 — Foundations

**Goal:** a scaffolded repository with contracts and storage in place.

Scope:

- `pyproject.toml`, Python 3.12 venv, Ruff, Pytest; `.gitignore` excluding databases, uploads, logs, `.env`, virtual environments.
- Pydantic contracts: `SourceDocument`, `InvoiceDraft`, `NormalizedInvoice`, `ValidationFinding`, `ApprovalDecision`, `ProcessingResult` (decimal amounts serialized as strings).
- SQLite schema for all logical tables; idempotent seed of WidgetA=15, WidgetB=10, GadgetX=5, FakeItem=0 that never silently resets existing data.
- Pure validation functions: required fields, decimal arithmetic, quantity aggregation, inventory comparison.

Exit criteria:

- [x] `pip install` and seed script work from a clean clone. (Verified 2026-11-01 with `uv sync`; see `docs/development.md`.)
- [x] Unit tests cover arithmetic, aggregation, and seed idempotence. (`tests/test_validation_arithmetic.py`, `tests/test_validation_inventory.py`, `tests/test_seed.py`; 75 tests total.)

Covers: A03 (partial), P02, P03 (logic only).

### Phase 1 — Walking skeleton (offline, one invoice)

**Goal:** INV-1001 TXT flows through the CLI to a persisted mock receipt in offline mode.

Scope:

- `main.py` with `--invoice_path`; proposed options for mode, database path, output path, and evaluation date (final names fixed here).
- LangGraph graph with all four agent nodes, typed state, and conditional routing to terminal states.
- Offline reasoning simulator, clearly labeled; no model SDK initialization or network access in this mode.
- Guarded payment service: rereads persisted state, atomic transaction, uniqueness constraint per business invoice identity.
- JSONL structured events (stage, run ID, source, status, duration, mode) plus a separate final JSON result.

Exit criteria:

- [ ] `python main.py --invoice_path=data/invoices/invoice_1001.txt` yields `paid_mock` with a USD 5,000.00 receipt.
- [ ] Rerunning the same file returns the existing outcome; no second payment.
- [ ] Offline test fails on any attempted network access.

Covers: A05, A07 (structure), A08, A09, P05 (exact-file case), P06 (states).

### Phase 2 — Full corpus and data integrity

**Goal:** every supplied fixture produces its expected outcome in offline mode.

Scope:

- Parsers: TXT, JSON, both CSV layouts (field/value rows and row table with footer), XML via `defusedxml`, text-based PDF via `pdfplumber`.
- Normalization with provenance: raw value, normalized value, evidence location, rule/model source. Covers label typos, item aliases, spaced item names, `2O26` / `3,500.O0` OCR artifacts.
- Currency handling (USD assumption recorded; EUR routed to review), date handling with a test-controlled clock.
- Duplicate and revision handling: source hash, business identity (vendor + invoice number), semantic hash; alternate formats and revised versions never create a second payment.
- Input limits: 10 MiB, 25 PDF pages, 200 lines; malformed, oversized, image-only, and encrypted inputs fail with an actionable reason.
- Fixture-driven regression suite mirroring the [sample acceptance matrix](requirements.md#sample-acceptance-matrix); verify actual PDF extraction against committed bytes.

Exit criteria:

- [ ] All 20 supplied files accounted for with asserted outcomes, including expected failures.
- [ ] INV-1013 aggregates WidgetA=22, WidgetB=18, GadgetX=9 and reports the USD 50.00 discrepancy.
- [ ] INV-1004/1004-revised, 1011 TXT/PDF, 1012 TXT/PDF, 1013 JSON/PDF yield at most one payment per identity.
- [ ] INV-1014 stays EUR and is not paid.

Covers: A01, A02, A03, P01, P02, P03, P04, P05, P09 (input limits), P10.

### Phase 3 — Live Grok reasoning

**Goal:** the primary demo runs on real Grok with tool use, structured outputs, and observable self-correction.

Prerequisite: xAI credentials, a confirmed current model, and a live-testing budget. Without these this phase is blocked; simulation must not be relabeled as live.

Scope:

- xAI SDK adapter behind the reasoning interface; model configurable; credentials loaded only in live mode. Confirm SDK calls and model availability from official xAI documentation.
- Whitelisted tool dispatcher that validates arguments and authorization; invoice text treated as untrusted (prompt-injection cannot change rules or trigger payment).
- One extraction-repair retry; initial recommendation → critique → at most one revised recommendation; independent deterministic eligibility gate afterwards.
- Bounds: 30 s request timeout, ≤ 2 transport attempts, ≤ 6 model calls per invoice.
- Live failure leaves the invoice unpaid in a recoverable error state with explicit retry; switching to offline creates a separately labeled run that never inherits live approval.
- Persist concise decision summaries and cited evidence, never hidden chain-of-thought or secrets.

Exit criteria:

- [ ] Explicitly invoked live smoke test passes and reports provider/model without exposing secrets.
- [ ] Controlled tests cover malformed model output, budget exhaustion, timeout, and provider failure; none produce payment.
- [ ] Payment-safety tests pass regardless of model wording.

Covers: A04, A06, A07, P09, P11, P15.

### Phase 4 — Human review workflow (service layer)

**Goal:** corrections and high-value approvals work end-to-end through the shared service, before any UI.

Scope:

- `Correction` and `HumanReview` contracts; versioned invoice records; original source bytes never edited.
- Evidence-backed corrections with required reason, reviewer, timestamp, before/after values; each correction invalidates prior approval and reruns validation and approval/critique.
- Source-document errors cannot be disguised as extraction corrections; they require a corrected invoice.
- Identity corrections check both old and new identities for prior payment.
- `awaiting_human_approval` for otherwise-valid USD totals above 10,000; approve/decline bound to the current validated version; stale or repeated requests rejected or return the existing outcome.
- New fixtures: valid USD 10,000.00 and 10,000.01, an evidence-backed extraction mistake, an actual source-document error, a correction after approval, repeated/stale approval requests, a live-provider failure.

Exit criteria:

- [ ] 10,000.00 auto-pays; 10,000.01 waits unpaid until explicit human approval.
- [ ] Human approval cannot override any hard blocker.
- [ ] Stale approval after a correction cannot reach payment.

Covers: P13, P14, plus completion items 2 and 5.

### Phase 5 — API and operator UI

**Goal:** the approved mockup becomes a working React + TypeScript app backed by FastAPI.

Scope:

- FastAPI endpoints for submission/sample selection, run progress, invoice list/detail, findings, decisions, receipts, result download, corrections, and approve/decline. Policy stays in the backend.
- React views from [mockup.md](mockup.md): empty workspace, add invoice, processing, overview, invoice detail (success, rejection), needs review, plus duplicate, version conflict, unsupported, oversized, missing fields, contradictory totals, provider unavailable, processing failure, empty filter, and loading states.
- Persistent execution-mode badge; historical runs keep their original mode label; "Mock payment" labels throughout.
- Dashboard counts distinguish documents, unique invoices, runs, and paid invoices.
- [Style guide](styleguide.md) tokens (black canvas, `#009A6C` accent, Aventa → Arial fallback), status by text and icon rather than color alone, keyboard access, reduced motion, responsive layouts at the documented breakpoints.
- Refreshes and repeated requests never trigger processing or payment.

Exit criteria:

- [ ] Every state visually checked at desktop and narrow widths with real persisted data.
- [ ] Browser coverage for correction/revalidation, human approval, and stale/repeated action rejection.
- [ ] Frontend type check and production build pass; runtime assets are local.

Covers: P07, P08 (audit views), P12.

### Phase 6 — Hardening and submission

**Goal:** a reproducible, documented public submission.

Scope:

- Whole-corpus runs, error injection, malformed input, payment replay, threshold boundaries, and offline-network tests.
- Audit trail completeness check: source hash, run identity, evidence, tool outcomes, normalization, critique summary, policy version, mode, payment result (P08).
- Repository README additions: architecture, setup, seed, run, test, demo instructions, assumptions, limitations, example results. Original assignment text preserved.
- Rehearse the [evaluator walkthrough](mockup.md#suggested-evaluator-walkthrough) on fresh, explicitly initialized demo data.
- Resolve or disclose the offline/LLM interpretation and other open questions below.
- Publish to a public github.com repository; confirm no keys, ledgers, uploads, or `.env` files are committed.

Exit criteria:

- [ ] Clean-install offline run covers every supplied file with failures explained.
- [ ] Live demo verified separately from offline tests.
- [ ] Public repository URL reproduces the documented results.

Covers: A10, P08, P10, completion items 1, 3, 6, 7.

### Optional — after core completion

Measured performance metrics, illustrative savings with visible assumptions, additional adversarial fixtures, real local-model inference, richer version comparison, batch submission.

## 8. Requirement traceability

| Requirement | Phase |
| --- | --- |
| A01 ingest formats | 2 |
| A02 field extraction | 2 |
| A03 SQLite inventory validation | 0, 2 |
| A04 approval + critique | 3 |
| A05 mock payment / rejection log | 1 |
| A06 Grok provider | 3 |
| A07 multi-agent, tools, self-correction | 1, 3 |
| A08 offline runtime | 1 |
| A09 CLI + structured logs | 1 |
| A10 public GitHub submission | 6 |
| P01 XML input | 2 |
| P02 decimal arithmetic | 0, 2 |
| P03 item aggregation | 0, 2 |
| P04 normalization evidence | 2 |
| P05 duplicate prevention | 1, 2 |
| P06 distinct outcomes | 1 |
| P07 operator UI | 5 |
| P08 audit trail | 1–6 (verified in 6) |
| P09 bounded work | 2, 3 |
| P10 regression tests | 2, 6 |
| P11 real Grok demo | 3 |
| P12 React + FastAPI per mockup | 5 |
| P13 reviewer corrections | 4 |
| P14 human approval above USD 10,000 | 4 |
| P15 recoverable model failures | 3 |

## 9. Success criteria

From [requirements — evaluation and completion](requirements.md#evaluation-and-completion):

1. Clean-install offline run over every supplied file, failures explained.
2. Tested approved-to-payment path and rejected/review/duplicate-to-no-payment paths, including restarts.
3. Separate unit, integration, and real Grok verification.
4. React + TypeScript UI, FastAPI backend, and CLI sharing one Python service.
5. Verified correction/revalidation, high-value approval, stale-approval rejection, and live-failure paths.
6. Documented architecture, setup, assumptions, limitations, and example results.
7. Offline/LLM interpretation resolved or disclosed.

## 10. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Evaluator rejects offline simulator as "LLM integration" | Agentic-sophistication score | Live Grok is the primary demo; simulator labeled; interpretation disclosed. |
| No xAI credentials or budget | Phase 3 blocked | Treat as delivery blocker; another provider is allowed by the brief but needs a decision. |
| PDF extraction differs from TXT/generator expectations | Wrong outcomes for 1011–1013 | Verify against committed bytes in Phase 2. |
| Scope (React + FastAPI + review workflow) exceeds available time | Incomplete submission | Phases deliver working increments; CLI + corpus are shippable alone. |
| Model output steers payment | Safety failure | Deterministic gate, whitelisted tools, payment service rechecks persisted state. |

## 11. Open questions

From [constraints](contraints.md#decisions-to-revisit-before-implementation-or-submission) and [decisions](decisions.md#remaining-open-details):

1. Does an offline simulator plus tested live integration satisfy the brief, or is real offline inference required?
2. Grok credentials, current supported model, and live-testing budget.
3. Deadline, available hours, and target evaluator machine.
4. EUR settlement support versus review-only handling.
5. Actual PDF extraction results versus generator source.
6. Evaluator view on revision handling and simplified inventory semantics.
7. Exact dependency versions and detailed API contracts (settled during Phases 0 and 5).
