# P0-08 — Item aggregation and inventory comparison

Phase: 0 · Status: done · Depends on: P0-03, P0-05 · Requirements: A03, P03

## Context

Quantities are aggregated per canonical item within an invoice before stock checks, while each original line and its price are kept. Unknown items, zero stock, and overstock requests block payment. Inventory is a fixed snapshot and is never decremented ([constraints — dataset limitations](../contraints.md#dataset-and-business-limitations)).

## Scope

In `validation.py`:

- `aggregate_quantities(lines) -> dict[str, AggregatedItem]`: total quantity per canonical item plus references to the contributing lines. Operates on already-canonical names; alias mapping is Phase 2.
- `check_inventory(aggregated, stock: dict[str, int | None]) -> list[ValidationFinding]`: pure comparison taking stock from P0-04 `get_stock`:
  - `unknown_item` blocker when stock is `None`.
  - `zero_stock` blocker when stock is 0.
  - `quantity_exceeds_stock` blocker with requested and available values.
- A thin wrapper that reads stock from a connection and calls the pure function, so most tests need no database.

## Out of scope

Alias normalization (WidgetA rush order in INV-1010), stock decrement, price checks.

## Acceptance criteria

- [ ] INV-1013 lines aggregate to WidgetA=22, WidgetB=18, GadgetX=9; all three exceed seed stock.
- [ ] INV-1002: GadgetX 20 > 5 → `quantity_exceeds_stock`.
- [ ] INV-1003: FakeItem → `zero_stock`. INV-1008: SuperGizmo and MegaSprocket → `unknown_item`. INV-1016: WidgetC → `unknown_item`.
- [ ] INV-1001: WidgetA 10, WidgetB 5 → no findings.
- [ ] The integration test against a seeded temporary database confirms no stock values change.
