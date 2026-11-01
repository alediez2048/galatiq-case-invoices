# P0-03 — Core Pydantic data contracts

Phase: 0 · Status: done · Depends on: P0-02 · Requirements: P04, P06, P08 (shape only)

## Context

[System design — core data contracts](../systemsdesign.md#core-data-contracts) defines the shared types every stage passes around. A key rule: the draft must be able to hold invalid or missing values so evidence is not lost when a strict payable schema would reject it.

## Scope

`src/invoice_processing/schemas.py` with:

- `EvidenceRef`: source ID, location (line, row, page, JSON path, or XML path), raw text snippet.
- `SourceDocument`: source ID, content hash (SHA-256), original name, format (`txt`, `json`, `csv`, `xml`, `pdf`), page/row references, extracted text, parser version.
- `InvoiceDraft`: raw vendor, invoice number, dates, currency, stated subtotal/tax/shipping/total, raw line items (description, quantity, unit price, line total — all optional and allowed to be invalid), extraction issues, evidence refs. No validation that would discard values.
- `NormalizationEvent`: field, raw value, normalized value, evidence, provenance (`rule:<name>` or `model:<provider>`).
- `NormalizedInvoice`: canonical vendor key, invoice number, optional revision, normalized dates, currency, canonical line items, stated totals, computed totals, normalization events. Money fields use the P0-02 type.
- `ValidationFinding`: stable `code`, `severity` (`info` | `warning` | `review` | `blocker`), field/item, expected, observed, evidence, resolution status. `review` routes to `needs_review`; `blocker` routes to `rejected`; precedence in the gate is blocker > review > high-value threshold (added 2026-11-01 from plan review).
- `ApprovalDecision`: initial and final recommendation, critique summary, reasons, policy version, execution mode (`live` | `offline`), provider/model when live.
- `ProcessingResult`: run ID, invoice ID, status, findings, decision, optional mock receipt, timings, errors.
- Two status enums (revised 2026-11-01 during plan review; the system design conflated them):
  - `RunStatus` — lifecycle of one processing attempt: `received`, `extracted`, `validated`, `approval_pending`, `approved`, `awaiting_human_approval`, `paid_mock`, `rejected`, `needs_review`, `failed`, `duplicate`.
  - `InvoiceStatus` — current business state of one invoice identity: `processing`, `paid_mock`, `rejected`, `needs_review`, `awaiting_human_approval`, `failed`, `superseded`. A `duplicate` run never changes the invoice's status; `superseded` is set by a corrected submission (P4-05).
- `FindingCode` enum seeded with the codes Phase 0 checks emit (see P0-06, P0-07, P0-08); later phases add more. Codes are stable identifiers, never prose.

## Out of scope

`Correction` and `HumanReview` contracts (P4). Parsing logic. Persistence mapping (P0-04 stores serialized payloads).

## Acceptance criteria

- [ ] An `InvoiceDraft` can be built from INV-1009's content (missing vendor/date, negative quantity and total) without raising.
- [ ] All money fields serialize as strings; `model_json_schema()` succeeds for every contract.
- [ ] Round-trip tests (`model_dump_json` → `model_validate_json`) pass for each contract.
- [ ] Enums and finding codes are importable from one module and documented with one-line descriptions.
