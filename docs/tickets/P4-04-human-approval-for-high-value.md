# P4-04 — Human approval for high-value invoices

Phase: 4 · Status: done · Depends on: P4-01, P1-05, P3-06 · Requirements: P14

## Context

Otherwise-valid USD totals above 10,000 require explicit human approval after the agent recommendation and critique; they wait unpaid in `awaiting_human_approval`. Human approval cannot override any hard blocker, a model recommendation never counts as human approval, and payment must reject approvals for stale versions ([decisions — round 2](../decisions.md#round-2--implementation-consequences)).

## Scope

In `review.py`:

- `approve(invoice_id, expected_version, reviewer, reason)` and `decline(...)`:
  - Allowed only when status is `awaiting_human_approval` and `expected_version` is current; otherwise `action_not_allowed` or `stale_version`.
  - Writes the `HumanReview` row, then re-runs `policy.evaluate(invoice, findings, recommendation, human_review=review)` on the persisted version: any blocker or review finding → still refused (the review row is kept as audit of the attempt); otherwise the gate now returns `approved`.
  - `approve` then calls the payment service; `decline` sets `rejected` with the reason.
  - Also handles the `model_disagreement` wait from P1-04 (clean invoice the model rejected): same approve/decline actions.
- `payments.pay` (P1-05) already requires the matching `HumanReview(approve)` row inside its transaction for totals > 10,000.00 and for `model_disagreement`; this ticket adds the tests that prove it.
- Repeated `approve` on a paid invoice returns the existing receipt; no second payment.
- Human review never holds a database transaction open while waiting.

## Acceptance criteria

- [x] `valid_10000_00.json` (from P3-06) → `paid_mock` without human action. (`tests/test_human_approval.py::test_10000_00_auto_pays`, `tests/test_review_acceptance.py::test_10000_00_pays_with_no_human_action`)
- [x] `valid_10000_01.json` → `awaiting_human_approval`; `approve` → `paid_mock`; second `approve` → same receipt. (`tests/test_human_approval.py::test_10000_01_waits_then_approve_pays_once`)
- [x] `decline` → `rejected` with reason; later `approve` refused. (`tests/test_human_approval.py::test_decline_rejects_and_later_approve_refused`)
- [x] Approval for version 1 after a correction created version 2 → `stale_version`, no payment. (`tests/test_human_approval.py::test_approve_stale_after_correction`)
- [x] Calling `pay` directly for a > 10,000 invoice without a matching `HumanReview` raises. (`tests/test_human_approval.py::test_pay_without_human_review_over_threshold_raises`, `::test_pay_refuses_superseded_version_even_with_forged_approval`)
- [ ] Two concurrent `approve` calls → exactly one payment (thread test). **Thread tests deferred** (cut line); the `payments.invoice_id UNIQUE` guard and the in-transaction version check remain.

## As built (2026-11-02)

- Calls: `review.approve(invoice_id, expected_version, reviewer, reason, db_path=...)` and `review.decline(...)`. Each writes the `HumanReview` row and a `human_review` run in one transaction, then runs it from validation with no transaction open. The run revalidates deterministically and reaches the gate with the waiting run's final recommendation; it never calls a model (`tests/test_human_approval.py::test_approval_never_calls_a_model`, `::test_approval_revalidates`).
- Decline is a gate outcome: `R3_human_declined` plus the blocker finding `human_declined`. A repeated approve of the paid version returns the paying run's result and writes nothing; any other version gets `stale_version`.
- The gate counts a human review only when its `invoice_id`, `version` and `policy_version` all match (P4-04 carry-over, `tests/test_policy.py::test_human_review_for_other_invoice_does_not_count`); the approval-node path is covered by `tests/test_human_approval.py::test_10000_01_waits_then_approve_pays_once` (`human_review_applied` event). `payments.pay` refuses any version that is not `invoices.current_version` (`stale_version`).
- An interrupted human-review run is retried on its version with `service.retry_run(run_id, None, ...)`, with no model call and no credentials (`tests/test_human_approval.py::test_interrupted_approve_is_retried_without_a_model_or_file`); a retry whose version is no longer current is refused `not_current`. `approve` / `decline` / `submit_correction` take an optional `on_run_started(run_id)` callback.
