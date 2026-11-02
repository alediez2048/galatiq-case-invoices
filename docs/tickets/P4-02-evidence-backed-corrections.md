# P4-02 — Evidence-backed correction and revalidation

Phase: 4 · Status: done · Depends on: P4-01, P1-07, P3-05 · Requirements: P13

## Context

Reviewers may correct **extraction** mistakes supported by the original source. Errors in the vendor document itself require a corrected invoice; the operator must not rewrite the source to make numbers pass. Every correction invalidates earlier approval and reruns validation and approval/critique ([requirements — business policy](../requirements.md#business-policy)).

The key test: a correction must make the extracted value match what the source actually says. INV-1013's stated total 22,562.80 is what the document says; "correcting" it to 22,512.80 is a source error, not an extraction error.

## Scope

`src/invoice_processing/review.py`:

- `submit_correction(invoice_id, expected_version, field, new_value, evidence_location, reason, reviewer) -> ProcessingResult`:
  1. Reject if `expected_version` ≠ current version (`stale_version`), returning the current record.
  2. Reject if the invoice is paid (`already_paid`). Corrections are allowed on `needs_review`, `rejected`, and `awaiting_human_approval` invoices, since a rejected invoice may carry a missing-field or stock blocker caused by misextraction; what makes a correction legitimate is the evidence check in step 3, not the current status.
  3. Evidence check (reuses the P3-05 deterministic verifier): the source text at `evidence_location` must support `new_value` under documented rules. Otherwise `correction_not_in_source` with the message "This value is not what the invoice says. Submit a corrected invoice from the vendor."
  4. Create the new version, write the `Correction`, invalidate prior recommendations/approvals for payment purposes, and run a new processing run using the P1-07 `start="validation"` entry point (validation → approval/critique → gate → payment stage) on the new version in the invoice's original mode. A corrected invoice that is now clean and ≤ USD 10,000 may auto-pay; the UI copy must say so (P5-09).
- Correctable fields: vendor, invoice number, dates, currency, item name, quantity, unit price, stated subtotal/tax/shipping/total, each only as extraction fixes.
- Multiple fields in one request are allowed only if each has its own evidence; all-or-nothing.

## Acceptance criteria

- [x] Constructed ambiguous-OCR fixture (`$3,5O0.00` on a line where qty × price disagrees, P2-08) → `needs_review`; correcting to the value the line evidence supports → new version, revalidated, final status from the gate. (`tests/test_corrections.py::test_ocr_ambiguous_correction_is_revalidated_not_cleared`, `::test_extraction_mistake_corrected_then_paid`)
- [x] INV-1013: correcting stated total to 22,512.80 → `correction_not_in_source`; no new version. (`tests/test_corrections.py::test_inv_1013_total_correction_refused`)
- [x] Correction with a stale `expected_version` → `stale_version`; nothing written. (`tests/test_corrections.py::test_stale_expected_version_writes_nothing`)
- [x] Original source bytes and version 1 payload are unchanged after a correction (hash check). (`tests/test_corrections.py::test_source_bytes_and_v1_payload_unchanged`)

## As built (2026-11-02)

- Call: `review.submit_correction(CorrectionRequest(invoice_id, expected_version, changes=[FieldChange(field, new_value, evidence_location), ...], reason, reviewer), db_path=...)`. Up to 10 changes, all or nothing (`tests/test_corrections.py::test_all_or_nothing_multi_field`). Refusals raise `review.ReviewRefused(code, message, current)` and write nothing.
- Evidence rule: the cited location must resolve in the stored source text, must use the scheme the parser records for that format (TXT `line:N`, PDF `page:P,line:N`, CSV `row:N[,col:…]`, JSON `$…`, XML `/…`), is canonicalized before comparison, and must not be another field's recorded location (`evidence_location_mismatch`). The located text must then support the value: in text formats a money token on the line must carry the same digits and sign (so `$3.500,00` supports `3500.00`, and a parenthesized amount is never evidence); JSON and XML money is the structured scalar parsed as `Decimal` and compared to the cent; OCR digit fixing (`O` → `0`) applies only to money, quantities and dates. Otherwise `correction_not_in_source`.
- Not correctable here: identity changes to `vendor` / `invoice_number` (`identity_correction_deferred`, P4-03), and `currency` when the document states one (`field_not_correctable`). Sources processed before Phase 4 have no stored text or field evidence (`source_text_unavailable`, `evidence_unavailable`).
- The correction run starts at validation, carries the base run's ingestion-stage findings except those naming a corrected field, and reruns approval and critique in the base run's mode and evaluation date. A failed live correction run is retried on the same version with `service.retry_run(run_id, None, ...)` (`tests/test_corrections.py::test_failed_live_correction_retried_on_same_version`).
