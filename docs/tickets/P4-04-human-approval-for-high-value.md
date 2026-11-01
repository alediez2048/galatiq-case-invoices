# P4-04 — Human approval for high-value invoices

Phase: 4 · Status: todo · Depends on: P4-01, P1-05, P3-06 · Requirements: P14

## Context

Otherwise-valid USD totals above 10,000 require explicit human approval after the agent recommendation and critique; they wait unpaid in `awaiting_human_approval`. Human approval cannot override any hard blocker, a model recommendation never counts as human approval, and payment must reject approvals for stale versions ([decisions — round 2](../decisions.md#round-2--implementation-consequences)).

## Scope

In `review.py`:

- `approve(invoice_id, expected_version, reviewer, reason)` and `decline(...)`:
  - Allowed only when status is `awaiting_human_approval` and `expected_version` is current; otherwise `action_not_allowed` or `stale_version`.
  - Re-runs the deterministic gate on the persisted version before recording; any blocker → refused.
  - `approve` writes a `HumanReview` and calls the payment service; `decline` writes the review and sets `rejected` with the reason.
- Extend `payments.pay` (P1-05): for totals > 10,000.00 it requires a `HumanReview(approve)` bound to the same version and policy version, inside the payment transaction. Gate `approved` alone is insufficient above the threshold.
- Repeated `approve` on a paid invoice returns the existing receipt; no second payment.
- Human review never holds a database transaction open while waiting.

## Acceptance criteria

- [ ] `valid_10000_00.json` (from P3-06) → `paid_mock` without human action.
- [ ] `valid_10000_01.json` → `awaiting_human_approval`; `approve` → `paid_mock`; second `approve` → same receipt.
- [ ] `decline` → `rejected` with reason; later `approve` refused.
- [ ] Approval for version 1 after a correction created version 2 → `stale_version`, no payment.
- [ ] Calling `pay` directly for a > 10,000 invoice without a matching `HumanReview` raises.
- [ ] Two concurrent `approve` calls → exactly one payment (thread test).
