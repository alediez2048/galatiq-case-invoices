# P1-04 — Deterministic eligibility policy gate

Phase: 1 · Status: done · Depends on: P0-03, P0-02 · Requirements: A04 (rules), P06, P14 (routing only)

## Context

The final decision must not depend on model wording. An independent deterministic gate runs after recommendation and critique: any blocker prevents payment regardless of the recommendation ([system design — processing sequence step 8](../systemsdesign.md#processing-sequence)).

## Scope

`src/invoice_processing/policy.py`:

- `POLICY_VERSION` constant recorded on every decision.
- `HIGH_VALUE_THRESHOLD_USD = Decimal("10000.00")`.
- `evaluate(invoice, findings, recommendation, human_review: HumanReview | None = None) -> GateResult` (revised 2026-11-01 from plan review), evaluated in this precedence order:
  1. `rejected`: any finding with severity `blocker` (stock, arithmetic, missing required field, sign).
  2. `needs_review`: any finding with severity `review` (unsupported currency, ambiguous normalization, version conflict, unresolved relative date).
  3. `awaiting_human_approval`: no blocker/review findings and either (a) USD total **> 10,000.00** without a `HumanReview(approve)` bound to the current version and `POLICY_VERSION`, or (b) the final model recommendation is `reject` or `review` on an otherwise clean invoice (recorded as finding `model_disagreement`, warning). A human then approves or declines through P4-04.
  4. `approved`: no blocker/review findings, USD, and either total **≤ 10,000.00** with final recommendation `approve`, or total > 10,000.00 with a matching `HumanReview(approve)`.
- A model recommendation can never turn a blocker or review finding into `approved`, and a human review can never clear one either; it only satisfies the high-value or model-disagreement wait.
- Result lists the rule IDs that decided the outcome.

## Out of scope

Human approve/decline actions (Phase 4). Duplicate status (handled before the gate in P1-07).

## Acceptance criteria

- [ ] Clean USD 10,000.00 → `approved`; clean USD 10,000.01 → `awaiting_human_approval`; the same with a matching `HumanReview(approve)` → `approved`; with a review bound to a different version → still `awaiting_human_approval`.
- [ ] Any blocker + approve recommendation → `rejected`; any blocker + human approve → `rejected`.
- [ ] EUR invoice with no blockers → `needs_review`; EUR + human approve → `needs_review`.
- [ ] Clean invoice + model `reject` → `awaiting_human_approval` with `model_disagreement`.
- [ ] Table-driven tests cover each branch; no prose assertions.
