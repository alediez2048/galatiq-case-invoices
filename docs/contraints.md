# Constraints, assumptions, and open decisions

Status: baseline updated with [user-approved decisions](decisions.md). Filename follows the requested `contraints.md` spelling.

Related: [requirements](requirements.md), [system design](systemsdesign.md), [stack](techstack.md).

## Assignment constraints

- A working prototype must run locally; cloud deployment is outside the assignment.
- Runtime must assume no external APIs. Initial dependency installation is assumed to allow internet access; a fully air-gapped install would need a prepared package cache and any model weights.
- Inventory validation must use persistent SQLite with at least the four specified seed records.
- Preferred reasoning provider is Grok; another model is allowed without an xAI key.
- Payment is simulated. No bank connection, funds transfer, email sending, or production credentials are needed.
- Command-line execution and structured logs/results are required.
- Submission must be a public repository on github.com.

## Primary ambiguity: LLM integration versus offline execution

The assignment asks for API-backed LLM reasoning while also prohibiting external API dependencies at runtime. These cannot both describe a live hosted-model call during an offline run.

Agreed project interpretation (not evaluator confirmation):

- Explicitly selected `offline` mode uses local parsers, deterministic validation, and a clearly labeled simulated reasoning adapter. No model SDK initialization or network calls occur in this mode.
- The primary demonstration uses real Grok in `live` mode through the typed reasoning interface, with tool calling and schema validation. It requires explicit configuration, credentials, and internet access. No hosted-model transmission begins merely by opening the app.
- Never silently switch a failed live run to simulation. Leave the invoice unpaid in a recoverable error state and offer an explicit retry. Switching to offline mode creates a separately labeled run and never inherits live approval.
- Simulation demonstrates workflow, contracts, and safeguards; it is not evidence of actual LLM reasoning or actual model self-correction.
- A local model could satisfy real inference without external APIs, but adds hardware, download, model-quality, and setup constraints. Defer selecting one until offline real inference is confirmed as necessary.

Open decision: confirm with the evaluator whether an offline simulator plus primary tested live integration satisfies the brief. Until clarified, treat this as an evaluation risk, not a resolved requirement.

## Dataset and business limitations

| Constraint | Consequence and proposed response |
| --- | --- |
| No purchase orders, receiving records, vendor registry, or trusted price master | Cannot claim real three-way matching, vendor authentication, or fraud detection. Validate only available evidence. |
| Inventory semantics are simplified | Compare requested quantities to seed stock as directed, although invoice approval in real procurement needs richer business data. Do not decrement stock when paying an invoice. |
| Repeated items | Aggregate quantities before stock comparison; retain each original line and its price. |
| Revised and repeated invoices | Treat vendor plus invoice number as one payment identity. Changed content requires revision handling, not an extra payment. |
| Multiple formats for the same invoice | Source hash detects identical files; invoice identity and semantic comparison detect alternate formats. |
| Historical and inconsistent dates | Use a test-controlled clock; preserve absolute dates; warn on overdue invoices; do not infer relative dates from the developer's current day. |
| No explicit currency on some samples | Record USD assumption from dataset context; explicit EUR remains EUR and is blocked from USD-only settlement. |
| Malformed values and OCR-like artifacts | Apply only traceable, bounded corrections; never fabricate missing vendor, totals, or dates. |
| PDF generator is textual, including its “scanned-style” sample | OCR-like text does not prove scanned-image support. Verify actual PDFs; image-only/encrypted/corrupt documents get explicit unsupported/review outcomes in MVP. |
| Public repository | Commit synthetic fixtures and code; exclude keys, local ledgers, uploads, environment files, and any real financial documents. |

## Proposed operational bounds

These are implementation defaults to test and adjust, not assignment mandates:

- Single local operator; React frontend and FastAPI backend are separate development processes, with a shared Python processing service for API and CLI. Serialize processing work for the initial implementation. No enterprise concurrency or multi-tenant guarantees. Reviewer identity is recorded for local audit purposes, not represented as enterprise authentication.
- Maximum 10 MiB per input, 25 PDF pages, and 200 invoice lines. Reject oversized inputs with a useful reason.
- One extraction-repair retry and one approval revision after critique; no unbounded agent conversations.
- Live model request timeout of 30 seconds; at most two transport attempts for transient failures. Never retry payment as a model tool.
- Set a total model-call budget per invoice and enforce it in orchestration; initial proposed ceiling is six calls including retries.
- Exact money arithmetic with decimal values; positive integer stock/quantities. Credit notes, fractional units, foreign exchange, and partial payments are out of scope.
- SQLite is the local source of truth. JSONL output is diagnostic/export data and must not independently determine payment eligibility.
- Mock payment and ledger writes must have atomic/idempotent behavior. This does not establish exactly-once guarantees for a future real bank API.

## Security and trust boundaries

Invoice text is untrusted data. Requests embedded in documents cannot change business rules, invoke arbitrary tools, approve an invoice, or authorize payment. Model suggestions are validated against typed schemas and deterministic policy. Parameterize SQL, constrain file access to supplied inputs, bound parser work, and disable external entity resolution for XML.

Only the payment service may invoke the mock payment function after rechecking persisted approval and validation state. Neither model output nor UI state alone authorizes payment. Store concise decision explanations and evidence, not hidden chain-of-thought or secrets.

Corrections must match evidence in the immutable original source. Every correction invalidates approval and requires fresh validation and agent review. A source error requires a corrected invoice, not an operator adjustment to make the numbers pass. Human approval is mandatory for otherwise-valid USD totals above 10,000 and cannot override stock, arithmetic, currency, or duplicate-payment blockers. Payment must reject approvals for stale versions.

A mode change never creates a second payment entitlement: duplicate protection remains across runs and modes. Use an explicitly separate demo database when independent offline and live demonstrations need separate mock receipts.

## Scope and delivery constraints

Deadline, available engineering hours, target evaluator machine, API availability, and model budget remain unknown. Start with a complete CLI flow, then fixture coverage and reliability, then UI. React + TypeScript and FastAPI are now in scope to preserve the approved UI. Controlled human corrections and high-value approval are also in scope. Avoid distributed queues, vector databases, cloud hosting, and generalized ERP integrations in the MVP.

The original README remains the assignment source. The design documents describe planned behavior. The existing HTML prototype demonstrates appearance and sample interactions only; it does not implement the newly approved backend or human-review workflow. Matt Pocock's project-workflow skill configuration is a separate setup task; it has not been installed or configured by creating these documents.

## Decisions to revisit before implementation or submission

1. Offline simulator acceptance versus mandatory real offline inference.
2. Available Grok credentials, current supported model, and permitted live testing budget.
3. Deadline and delivery sequencing for the agreed frontend/API and controlled human-review scope.
4. Whether to support EUR settlement or retain review-only handling.
5. PDF extraction results against the actual committed files, including generator/source differences.
6. Any evaluator clarification on revision handling and simplified inventory semantics.
