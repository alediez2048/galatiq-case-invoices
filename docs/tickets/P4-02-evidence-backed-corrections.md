# P4-02 — Evidence-backed correction and revalidation

Phase: 4 · Status: todo · Depends on: P4-01, P1-07, P3-05 · Requirements: P13

## Context

Reviewers may correct **extraction** mistakes supported by the original source. Errors in the vendor document itself require a corrected invoice; the operator must not rewrite the source to make numbers pass. Every correction invalidates earlier approval and reruns validation and approval/critique ([requirements — business policy](../requirements.md#business-policy)).

The key test: a correction must make the extracted value match what the source actually says. INV-1013's stated total 22,562.80 is what the document says; "correcting" it to 22,512.80 is a source error, not an extraction error.

## Scope

`src/invoice_processing/review.py`:

- `submit_correction(invoice_id, expected_version, field, new_value, evidence_location, reason, reviewer) -> ProcessingResult`:
  1. Reject if `expected_version` ≠ current version (`stale_version`), returning the current record.
  2. Reject if the invoice is paid (`already_paid`) or in a state with no correctable extraction issue.
  3. Evidence check (reuses the P3-05 deterministic verifier): the source text at `evidence_location` must support `new_value` under documented rules. Otherwise `correction_not_in_source` with the message "This value is not what the invoice says. Submit a corrected invoice from the vendor."
  4. Create the new version, write the `Correction`, invalidate prior recommendations/approvals for payment purposes, and run a new processing run (validation → approval/critique → gate) on the new version in the invoice's original mode.
- Correctable fields: vendor, invoice number, dates, currency, item name, quantity, unit price, stated subtotal/tax/shipping/total, each only as extraction fixes.
- Multiple fields in one request are allowed only if each has its own evidence; all-or-nothing.

## Acceptance criteria

- [ ] Constructed ambiguous-OCR fixture (`$3,5O0.00` on a line where qty × price disagrees, P2-08) → `needs_review`; correcting to the value the line evidence supports → new version, revalidated, final status from the gate.
- [ ] INV-1013: correcting stated total to 22,512.80 → `correction_not_in_source`; no new version.
- [ ] Correction with a stale `expected_version` → `stale_version`; nothing written.
- [ ] Original source bytes and version 1 payload are unchanged after a correction (hash check).
