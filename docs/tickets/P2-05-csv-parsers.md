# P2-05 — CSV parsers (field/value and row-table layouts)

Phase: 2 · Status: todo · Depends on: P1-01 · Requirements: A01, A02

## Context

Two CSV layouts exist:

- **Field/value (1006)**: header `field,value`; repeated `item`, `quantity`, `unit_price` rows, one group per line item; header fields before and totals after.
- **Row table (1007, 1015)**: header `Invoice Number,Vendor,Date,Due Date,Item,Qty,Unit Price,Line Total`; one row per line repeating invoice fields; footer rows with empty leading cells and the label (`Subtotal:`, `Tax (6%):`, `Total:`) in the `Unit Price` column. 1007 uses `MM/DD/YYYY` dates.

## Scope

- `parsers/csv_parser.py` with the `csv` module; detect layout from the header row. Unknown header → `unsupported_csv_layout`.
- Field/value: build line items by grouping each `item` row with the next `quantity` and `unit_price`. An incomplete group is an `incomplete_line_item` issue, never merged with the following item.
- Row table: invoice-level fields must agree across every row; a disagreement is `inconsistent_row_header` (blocker), not "first row wins". Footer rows are recognized by label and parsed into stated totals and tax rate.
- Evidence references are row numbers (and column names).
- Preserve row order.

## Acceptance criteria

- [ ] 1006 yields WidgetA ×5 @ 250.00 and WidgetB ×3 @ 500.00 (both retained), subtotal 2,750.00, tax 0.00, total 2,750.00.
- [ ] 1007 yields three lines, raw dates `01/28/2026`/`02/28/2026`, subtotal 14,750.00, tax 885.00 at 6%, total 15,525.00.
- [ ] 1015 yields three lines, subtotal 6,500.00, tax 0.00, total 6,500.00.
- [ ] A test CSV whose rows disagree on vendor produces `inconsistent_row_header`.
