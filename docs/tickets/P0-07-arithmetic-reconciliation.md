# P0-07 — Arithmetic reconciliation

Phase: 0 · Status: todo · Depends on: P0-02, P0-03 · Requirements: P02

## Context

Totals must be recomputed with decimal values when source fields permit, and contradictions reported without silently replacing source values. A discrepancy greater than one cent blocks payment; any tolerated rounding difference is recorded ([requirements — P02 and business policy](../requirements.md#project-requirements-added-for-a-reliable-mvp)).

## Scope

Pure function `reconcile_totals(invoice) -> (ComputedTotals, list[ValidationFinding])` in `validation.py`:

- Line total = quantity × unit price; compare with any stated line total (`line_total_mismatch`).
- Subtotal = sum of line totals; compare with stated subtotal (`subtotal_mismatch`).
- Tax: when a rate and a stated tax amount are both present, compare (`tax_mismatch`).
- Expected total = subtotal + tax + shipping; compare with stated total (`total_mismatch`).
- Differences of exactly ≤ 0.01 emit `rounding_tolerated` (info) with the difference; larger ones are blockers with expected and observed values.
- Missing inputs skip the dependent comparison and emit `arithmetic_unverifiable` (warning) naming what was missing; nothing is filled in.
- Stated values are never overwritten; computed values are returned separately.

## Out of scope

Price validation against a price master (none exists). Currency conversion.

## Acceptance criteria

- [ ] INV-1013 figures: line sum 21,040.00, tax 1,472.80, expected 22,512.80 vs stated 22,562.80 → `total_mismatch` blocker with difference 50.00.
- [ ] INV-1010 figures: 6,700.00 + 335.00 + 150.00 = 7,185.00 → no mismatch.
- [ ] INV-1009's contradictory subtotal yields `subtotal_mismatch`.
- [ ] A 0.01 difference yields `rounding_tolerated`; 0.02 yields a blocker.
