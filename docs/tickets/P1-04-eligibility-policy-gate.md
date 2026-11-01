# P1-04 — Deterministic eligibility policy gate

Phase: 1 · Status: todo · Depends on: P0-03, P0-02 · Requirements: A04 (rules), P06, P14 (routing only)

## Context

The final decision must not depend on model wording. An independent deterministic gate runs after recommendation and critique: any blocker prevents payment regardless of the recommendation ([system design — processing sequence step 8](../systemsdesign.md#processing-sequence)).

## Scope

`src/invoice_processing/policy.py`:

- `POLICY_VERSION` constant recorded on every decision.
- `HIGH_VALUE_THRESHOLD_USD = Decimal("10000.00")`.
- `evaluate(invoice, findings, recommendation) -> GateResult` returning one of:
  - `rejected`: any confirmed blocker (stock, arithmetic, missing required field, sign), or the final recommendation is reject.
  - `needs_review`: unresolved extraction ambiguity or non-USD currency.
  - `awaiting_human_approval`: no blockers, USD, total **> 10,000.00**.
  - `approved`: no blockers, USD, total **≤ 10,000.00**, final recommendation approve.
- A model recommendation of approve can never turn a blocker into `approved`; a recommendation of reject on a clean invoice yields `rejected` with that reason recorded.
- Result lists the rule IDs that decided the outcome.

## Out of scope

Human approve/decline actions (Phase 4). Duplicate status (handled before the gate in P1-07).

## Acceptance criteria

- [ ] Clean USD 10,000.00 → `approved`; clean USD 10,000.01 → `awaiting_human_approval`.
- [ ] Any blocker + approve recommendation → `rejected`.
- [ ] EUR invoice with no blockers → `needs_review`.
- [ ] Table-driven tests cover each branch; no prose assertions.
