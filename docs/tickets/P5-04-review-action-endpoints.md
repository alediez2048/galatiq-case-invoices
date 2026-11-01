# P5-04 — Review action endpoints

Phase: 5 · Status: todo · Depends on: P5-01, P4-02 – P4-05 · Requirements: P13, P14

## Context

Correction and approval requests carry the version the reviewer saw; stale requests are rejected and the current record is shown. Stale versions and hard blockers disable payment approval and are also rejected server-side ([mockup — screen 7](../mockup.md#screen-7--needs-review)).

## Scope

- `POST /api/invoices/{id}/corrections` → `review.submit_correction`.
- `POST /api/invoices/{id}/approve` and `/decline` → `review.approve` / `decline`.
- `POST /api/invoices/{id}/corrected-submission` (multipart) → P4-05 corrected-invoice path.
- All require `expected_version`, `reason`, `reviewer`, and an `Idempotency-Key`; repeated keys return the original response.
- `409` responses include the current invoice detail so the UI can refresh in place.
- Return the new run ID when a correction triggers revalidation, so the UI can show progress via P5-02.

## Acceptance criteria

- [ ] Approve with a stale version → 409 with the current version in the body; no payment.
- [ ] Approve on a `needs_review` (EUR) invoice → 409 `action_not_allowed`.
- [ ] Repeated approve with the same idempotency key → identical response, one payment.
- [ ] Correction not supported by the source → 422 `correction_not_in_source` with the mockup's guidance message.
