# P2-04 — JSON parser

Phase: 2 · Status: done · Depends on: P1-01 · Requirements: A01, A02

## Context

JSON fixtures (1004, 1004 revised, 1005, 1009, 1013, 1016) share a shape: `invoice_number`, `vendor: {name, address}`, `date`, `due_date`, `line_items: [{item, quantity, unit_price, amount?, note?}]`, `subtotal`, `tax_rate`, `tax_amount`, `total`, `currency`, `payment_terms`, optional `revision` and `notes`. 1009 has an empty vendor name, a null due date, and a negative quantity.

## Scope

- `parsers/json_parser.py` using the standard library; parse numbers with `parse_float=Decimal` so amounts never pass through float.
- Map fields into `InvoiceDraft` with JSON-path evidence (e.g. `$.line_items[3].quantity`).
- Preserve `revision` (e.g. `R1`) and per-line `note`; keep `notes` as evidence text.
- Treat `""` and `null` as missing, not as values; keep invalid values (negative quantity) in the draft.
- Unknown top-level keys are kept as evidence and listed as `unrecognized_field` (info).
- Duplicate keys in one object → extraction issue (use `object_pairs_hook`).

## Acceptance criteria

- [ ] All six JSON fixtures parse without raising.
- [ ] 1013 yields eight lines with notes preserved and stated total 22,562.80 as an exact decimal.
- [ ] 1004 revised carries `revision = "R1"`; 1004 base has none.
- [ ] 1009 yields missing vendor, missing due date, quantity −5, and stated total −250.00 in the draft.
