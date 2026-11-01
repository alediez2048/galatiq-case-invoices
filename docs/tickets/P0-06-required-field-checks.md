# P0-06 — Required-field and value-sign checks

Phase: 0 · Status: todo · Depends on: P0-03 · Requirements: A03 (data integrity), P06

## Context

Payment requires vendor, invoice identity, due date, currency, total, and complete valid line items. Quantities must be positive whole numbers, the total positive, and prices, tax, and shipping nonnegative. Missing values are never invented ([requirements — business policy](../requirements.md#business-policy)). Past absolute due dates warn rather than reject.

## Scope

Pure functions in `src/invoice_processing/validation.py` returning `list[ValidationFinding]`, no I/O:

- `check_required_fields(invoice)`: one blocker per missing field (`missing_vendor`, `missing_invoice_number`, `missing_due_date`, `missing_currency`, `missing_total`, `missing_line_items`, `incomplete_line_item`). Empty or whitespace-only strings count as missing (INV-1009's vendor is `""`, not null).
- `check_value_signs(invoice)`: `non_positive_quantity`, `non_integer_quantity`, `non_positive_total`, `negative_unit_price`, `negative_tax`, `negative_shipping`.
- `check_due_date(invoice, evaluation_date)`: `due_date_past` as a warning; evaluation date is always passed in, never read from the system clock.
- Each finding carries field/item, observed value, and evidence when the input has it.

## Out of scope

Date and currency parsing from raw text, USD assumption for missing currency, relative dates (all Phase 2). Arithmetic (P0-07).

## Acceptance criteria

- [ ] A model of INV-1001 produces no blockers.
- [ ] A model of INV-1009 produces blockers for missing vendor, missing due date, negative quantity, and non-positive total.
- [ ] `due_date_past` is a warning, not a blocker, and depends only on the passed evaluation date.
- [ ] Finding codes come from the P0-03 enum; tests assert codes and severities, not message text.
