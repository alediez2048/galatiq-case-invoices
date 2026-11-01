# P5-03 — Invoice, detail, and dashboard read endpoints

Phase: 5 · Status: todo · Depends on: P5-01 · Requirements: P07, P08, P12

## Context

Dashboard counts distinguish documents, unique invoices, runs, and paid invoices to avoid inflated metrics. Mock-paid amounts are summed per currency, never combined. Detail shows mode, source preview, extracted data, normalization changes, findings, decision/critique summary, receipt, and history ([mockup — screens 4 and 5](../mockup.md#screen-4--overview-with-results)).

## Scope

- `GET /api/overview`: counts by current outcome per unique invoice (`paid_mock`, `needs_review`, `awaiting_human_approval`, `rejected`, `failed`), plus documents, runs, duplicates; mock-paid totals keyed by currency; recent invoices.
- `GET /api/invoices?status=&mode=&q=&page=`: list with vendor, invoice number, total + currency, outcome, mode of latest run.
- `GET /api/invoices/{id}`: current version, extracted and normalized fields, normalization events (raw → normalized, provenance), findings with evidence, line items with requested vs available stock, decision (initial recommendation, critique, final, mode, provider/model), receipt, versions, corrections, human reviews, runs, allowed actions.
- `GET /api/sources/{source_id}/content`: readable text/rows for TXT/CSV/JSON/XML with evidence anchors; for PDF, extracted text plus the original file for preview.
- `GET /api/invoices/{id}/result.json`: downloadable persisted result (never transient UI state).
- `GET /api/review-queue`: wraps P4-05.

## Acceptance criteria

- [ ] After processing 1001, 1004, 1002, 1014 on a fresh DB: overview shows 4 unique invoices, 2 mock paid, 1 rejected, 1 needs review; mock-paid USD 6,890.00; EUR shown separately (none paid).
- [ ] Processing 1011 TXT then PDF counts 2 documents, 2 runs, 1 unique invoice, 1 paid.
- [ ] No endpoint returns hidden reasoning, prompts, or secrets (schema test over response models).
- [ ] Downloaded result JSON equals the persisted `ProcessingResult`.
