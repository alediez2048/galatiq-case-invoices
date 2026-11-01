# P1-05 — Guarded, idempotent mock payment service

Phase: 1 · Status: done · Depends on: P0-04, P1-02, P1-04 · Requirements: A05, P05

## Context

Only the payment service may call the mock payment, and only after rechecking persisted state. Neither model output nor caller state authorizes payment. The assignment's `mock_payment(vendor, amount)` prints and returns success ([README — mock payment API](../../README.md#mock-payment-api)).

## Scope

`src/invoice_processing/payments.py`:

- `mock_payment(vendor, amount)` matching the assignment's behavior (returns `{"status": "success"}`), with `amount` as `Decimal` and currency passed alongside.
- `pay(conn, invoice_id, version_id, run_id) -> PaymentResult`:
  1. Open `BEGIN IMMEDIATE` transaction.
  2. Reread persisted gate result for this run/version; require `approved` and USD. When the validated USD total is > 10,000.00 or the decision carries `model_disagreement`, additionally require a persisted `HumanReview(approve)` row bound to the same version and policy version (the row P4-04 writes); its absence raises even if the gate result says `approved`.
  3. If a payment already exists for the invoice identity, return it (no new receipt).
  4. Otherwise call `mock_payment`, insert the payment row with a generated receipt ID, decimal string amount, currency, version, and write a `payment_succeeded` audit event.
  5. Commit.
- `record_rejection(...)`: logs rejection reasons; never calls `mock_payment`.
- No retries of payment anywhere.

## Out of scope

Human-approved payment path (Phase 4). Real bank semantics.

## Acceptance criteria

- [ ] Paying an `approved` invoice twice returns the same receipt and calls `mock_payment` once (assert with a spy).
- [ ] Calling `pay` for a `rejected`, `needs_review`, or `awaiting_human_approval` run raises and creates no payment.
- [ ] A failure inside the transaction leaves no payment row and no `payment_succeeded` event.
- [ ] The uniqueness constraint from P0-04 still rejects a direct duplicate insert.
