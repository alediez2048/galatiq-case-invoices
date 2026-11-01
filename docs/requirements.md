# Project requirements

Status: implementation baseline updated after two user-approved grilling rounds. Backend functionality is not yet implemented; the HTML mockup is a visual prototype. See [agreed decisions](decisions.md).

## Sources and interpretation

The [original assignment](../README.md) is the source of mandatory requirements. The supplied [invoices](../data/invoices/) and [PDF generator](../data/generate_pdfs.py) inform acceptance cases. This document labels added product requirements separately from assignment requirements. Preserve the original assignment and fixtures.

The fictional business context is $2M annual processing losses, a 30% error rate, and five-day delays. These are scenario inputs, not measured outcomes or promised savings.

Related documents: [constraints](contraints.md), [system design](systemsdesign.md), [technology stack](techstack.md).

## Objective and users

Build a runnable local multi-agent invoice-processing prototype. An accounts-payable operator submits an invoice, sees extracted evidence and validation findings, and receives an approval/rejection and mock-payment result. A reviewer can understand every decision. An evaluator can reproduce the workflow from the public GitHub repository.

## Assignment requirements

| ID | Requirement | Acceptance evidence |
| --- | --- | --- |
| A01 | Ingest PDF and text invoices; exercise supplied CSV and JSON inputs too. | Each supported format yields structured results or an explicit actionable failure. |
| A02 | Extract vendor, amount, items with quantities, and due date despite inconsistent formatting. | Normalized fields retain source evidence; missing information is not invented. |
| A03 | Validate against persistent local SQLite inventory. | Seed WidgetA=15, WidgetB=10, GadgetX=5, FakeItem=0; report unknown items and excessive quantities. |
| A04 | Simulate VP approval through rules and a reflection/critique loop. | Record initial recommendation, critique, final decision, and concise supporting reasons. High-value scrutiny is demonstrated; $10,000 is the assignment's example threshold. |
| A05 | Pay approved invoices through a mock function; log rejection reasons. | Approved eligible invoice receives a mock receipt; rejected invoice never invokes payment. |
| A06 | Use Grok as preferred reasoning engine; another model is acceptable without a key. | A real provider integration supports structured outputs and tool calls. Simulator-only tests are not evidence of actual LLM operation. |
| A07 | Use multi-agent orchestration, tools, structured outputs, and self-correction. | Distinct ingestion, validation, approval, and payment responsibilities; bounded repair and critique paths are observable. |
| A08 | Run locally with no external APIs required at runtime. | Explicit offline mode completes without credentials or network access. See unresolved interpretation in constraints. |
| A09 | Expose the assignment's command-line interface and structured logs/results. | `python main.py --invoice_path=data/invoices/invoice_1001.txt` runs after documented setup. |
| A10 | Submit a working prototype through a public GitHub repository. | Reproducible install, seed, run, test, and demo instructions; publicly accessible submission URL. |

Python is preferred by the assignment. No particular orchestration framework or UI framework is mandatory.

## Project requirements added for a reliable MVP

| ID | Requirement | Acceptance evidence |
| --- | --- | --- |
| P01 | Support the supplied XML input as well as the four advertised formats. | INV-1014 parses; explicit EUR handling prevents accidental USD payment. |
| P02 | Validate arithmetic using decimal money values. | Recompute line totals, subtotal, tax, shipping, and total when source fields permit; report contradictions without silently replacing source values. |
| P03 | Aggregate repeated canonical items before stock checks. | INV-1013 totals WidgetA=22, WidgetB=18, GadgetX=9, all exceeding seed stock. |
| P04 | Preserve normalization and evidence. | Log raw and corrected values for known item aliases, date typos, and numeric OCR artifacts. Ambiguous changes require review. |
| P05 | Prevent duplicate mock payments across reruns, formats, and revisions. | Persistent invoice identity and payment uniqueness; altered revisions after payment are blocked for review. |
| P06 | Distinguish business rejection, unresolved review, and technical failure. | `rejected`, `needs_review`, `awaiting_human_approval`, `failed`, `duplicate`, and `paid_mock` are distinct outcomes. |
| P07 | Provide a local operator UI. | Select/upload invoice, inspect extracted fields and findings, view decision and receipt, filter results, and see execution mode. |
| P08 | Produce an audit trail. | Persist source hash, run identity, evidence, tool outcomes, normalization, checks, critique summary, policy version, mode, and payment result. Never log credentials or private model reasoning. |
| P09 | Bound model and parser work. | File/page limits, model timeouts, retry limits, malformed-output handling, and safe terminal failure. |
| P10 | Provide fixture-driven regression tests. | All supplied inputs accounted for, expected failures asserted, and payment safety tested independently of model wording. |
| P11 | Demonstrate real Grok reasoning as the primary demo. | Verify actual structured outputs, tool calls, and critique with the provider. Offline simulation remains a separate, explicitly selected mode. |
| P12 | Preserve the approved visual mockup in a React + TypeScript UI backed by FastAPI. | Dashboard, invoice evidence, workflow progress, and review interactions meet the visual baseline; CLI and API share the Python processing service. |
| P13 | Support controlled reviewer corrections and approval. | Record source evidence, reviewer, reason, time, old/new values, and version; revalidate changes; bind approval to the current validated version. |
| P14 | Enforce mandatory human approval above USD 10,000. | Valid 10,000.00 may auto-pay; valid 10,000.01 stays unpaid until explicit human approval. Hard blockers remain non-overridable. |
| P15 | Expose recoverable model failures without fallback. | Failed live reasoning leaves the invoice unpaid; explicit retry is available. Offline selection creates a separately labeled run. |

## Business policy

- Positive whole-number quantities; positive invoice total; nonnegative prices, tax, and shipping. Credit notes are outside MVP scope.
- Required payment fields: vendor, invoice identity, due date, currency, total, and complete valid line items. Missing fields block payment.
- Exact arithmetic uses decimal values rounded to the currency's minor unit. A discrepancy greater than one cent blocks payment; any tolerated rounding difference is recorded.
- Aggregate quantities per canonical item within an invoice. Inventory is a fixed validation snapshot, not decremented by invoice payment.
- Unknown items, zero stock, overstock requests, and inconsistent totals block payment. A vendor name or urgent wording is not proof of fraud.
- Otherwise-valid invoices greater than USD 10,000 require explicit human approval after the agent recommendation and critique. They wait unpaid in `awaiting_human_approval`. Clean, eligible invoices at or below USD 10,000 may proceed automatically to mock payment. The threshold is checked against the final validated USD total, including tax and shipping; a human cannot override a hard blocker.
- USD-only mock settlement for MVP. Missing currency may use a prominently recorded USD dataset assumption; explicit EUR is preserved and routed to review, never converted implicitly.
- Existing absolute past due dates generate warnings rather than automatic rejection. Relative dates such as “yesterday” stay unresolved without a trustworthy reference date.
- Reviewers may correct extraction mistakes supported by the original source, with a required reason and an immutable before/after audit record. Each correction invalidates earlier approval and reruns validation and the approval/critique workflow. Errors in the vendor document require a corrected invoice; the operator must not rewrite the original source. Unsupported EUR settlement and previously paid invoices remain blocked.

## Sample acceptance matrix

These expectations come from inspected TXT, JSON, CSV, XML and generator source. Actual PDF bytes still require extraction-based verification during implementation. Evaluate each unique invoice against a fresh seed snapshot; test duplicate behavior separately in a persistent ledger.

| Fixture | Expected checks |
| --- | --- |
| 1001 TXT | Clean USD 5,000 invoice; inventory and totals pass. |
| 1002 TXT | Normalize misspelled labels; GadgetX 20 > 5; USD 15,000 requires scrutiny but stock failure blocks payment; inconsistent terms recorded. |
| 1003 TXT | FakeItem 100 > 0; unresolved relative due date; urgent wording is a risk signal only; no payment. |
| 1004 JSON | Base version inventory and USD 1,890 total pass. |
| 1004 revised JSON | Inventory and USD 5,940 total pass independently; revision is not a second payable invoice alongside the base version. |
| 1005 JSON | GadgetX 8 > 5; USD 15,225 high-value check; no payment. |
| 1006 CSV | Repeated field/value rows retain both items; USD 2,750 passes. |
| 1007 CSV | Row table and footer parse; WidgetA 20 > 15, WidgetB 15 > 10; USD 15,525 passes arithmetic, fails stock. |
| 1008 TXT | Unknown SuperGizmo and MegaSprocket; stated USD 9,900 agrees with arithmetic but inventory fails. |
| 1009 JSON | Missing vendor/date, negative quantity/total, contradictory subtotal; no invented repairs or payment. |
| 1010 TXT | Explicit alias for WidgetA (rush order); combined quantity 12; USD 6,700 + 335 + 150 = 7,185. Price variation alone is not invalid without a price master. |
| 1011 TXT/PDF | Clean USD 3,000 invoice; second representation must not trigger another payment. |
| 1012 TXT/PDF | Evidence-backed normalization of spaced item names, `2O26`, and `3,500.O0`; USD 9,975; unresolvable ambiguity goes to review. |
| 1013 JSON/PDF | Repeated quantities exceed stock. JSON lines sum to 21,040; tax is 1,472.80; expected total 22,512.80 differs from stated 22,562.80 by 50. Generator also adds 50 to PDF total. |
| 1014 XML | Explicit EUR 4,125; quantities and arithmetic pass; unsupported settlement currency requires review. |
| 1015 CSV | Footer totals and USD 6,500 invoice pass. |
| 1016 JSON | Unknown WidgetC; total USD 3,233 is arithmetically consistent; no payment. |

## Evaluation and completion

The assignment evaluates functionality, code quality, agentic sophistication, shipping mindset, presentation, differentiation, and UI/UX. Demonstrate each with runnable behavior, focused tests, audit views, and a short demo narrative.

Completion requires:

1. A clean-install offline run covering every supplied file, with failures explained rather than swallowed.
2. A tested approved-to-payment path and rejected/review/duplicate-to-no-payment paths, including restarts.
3. Separate unit, integration, and real Grok-provider verification. A simulated run cannot satisfy the primary live-demo requirement; unavailable credentials are a delivery blocker, not an excuse to relabel simulation.
4. A React + TypeScript UI preserving the approved mockup, a FastAPI backend, and the required CLI sharing the same Python business logic.
5. Verified correction/revalidation, high-value approval, stale-approval rejection, and live-provider failure paths.
6. Documentation of architecture, setup, assumptions, limitations, and example results in the public fork.
7. Explicit resolution or disclosure of the offline/LLM interpretation before submission.

Additional acceptance fixtures must include otherwise-valid totals of USD 10,000.00 and USD 10,000.01, an evidence-backed extraction mistake, an actual source-document error, a correction after approval, repeated/stale approval requests, and a live-provider failure. Supplied high-value invoices also have blockers, so they alone cannot demonstrate the eligible human-approval path.

Optional after core completion: measured performance metrics, illustrative savings with visible assumptions, additional adversarial fixtures, and real local-model execution. No deadline or implementation-hour budget has yet been supplied.
