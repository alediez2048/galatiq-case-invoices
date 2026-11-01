# P0-02 — Money and currency primitives

Phase: 0 · Status: todo · Depends on: P0-01 · Requirements: P02

## Context

Policy requires exact decimal arithmetic rounded to the currency's minor unit, money serialized as strings, and never binary floats ([requirements — business policy](../requirements.md#business-policy), [techstack](../techstack.md#selected-baseline)). Every later validation and payment step depends on these helpers.

## Scope

- `src/invoice_processing/money.py`:
  - Parse a source value (`str`, `int`, `Decimal`) into `Decimal`; reject `float` input with a clear error.
  - Quantize to a currency's minor unit with explicit `ROUND_HALF_UP` (document the choice).
  - Supported currency codes for MVP: `USD`, `EUR` (both 2 minor digits). Unknown codes raise rather than guess.
  - `ONE_CENT_TOLERANCE` constant and a helper that compares two amounts and returns the difference plus whether it exceeds tolerance.
- A Pydantic-compatible `Money` type (amount `Decimal` + currency code) or annotated `Decimal` field type that serializes to a string in JSON.
- Format helper for display (`USD 5,000.00`) used later by CLI/UI; no locale dependence.

## Out of scope

Parsing messy source text such as `$3,500.O0` (Phase 2 normalization). FX conversion (non-goal).

## Acceptance criteria

- [ ] `Decimal("0.1") + Decimal("0.2")` style cases produce exact results; float input is rejected.
- [ ] JSON round-trip of a money value preserves the exact string (e.g. `"22512.80"`).
- [ ] Tolerance helper: difference of `0.01` is within tolerance; `0.02` and `50.00` exceed it.
- [ ] Unit tests cover rounding at the half-cent boundary and unknown currency codes.
