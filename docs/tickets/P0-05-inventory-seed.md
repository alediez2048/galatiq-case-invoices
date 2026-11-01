# P0-05 — Idempotent inventory seed

Phase: 0 · Status: todo · Depends on: P0-04 · Requirements: A03

## Context

The [assignment](../../README.md#mock-inventory-database-required-setup) requires a persistent SQLite inventory with WidgetA=15, WidgetB=10, GadgetX=5, FakeItem=0. Its sample script uses a bare `INSERT`, which fails on rerun. The design requires seeding idempotently without silently resetting existing data, and demos need fresh, explicitly initialized databases without touching the user's ledger.

## Scope

- Seed data defined once in code (`src/invoice_processing/seed.py`) with exactly the four required records.
- `scripts/seed_inventory.py` (or a package entry point) with `--db PATH` (default `inventory.db`):
  - Creates the database and schema if missing (calls P0-04 `init_schema`).
  - Inserts missing seed items.
  - Leaves existing rows untouched; if an existing stock value differs from the seed, prints a warning naming the item and both values.
  - Prints a short summary: inserted, unchanged, differing.
- `--fresh` flag that only works on a path that does not yet exist (refuses to delete an existing file), for repeatable demo databases.
- Document the command in `docs/development.md`.

## Out of scope

Extra items, price or vendor tables (allowed by the assignment but not decided). Inventory decrement (inventory is a fixed snapshot).

## Acceptance criteria

- [ ] Running the seed twice on the same path succeeds; the second run reports four unchanged rows.
- [ ] Manually changing WidgetA to 99 then reseeding keeps 99 and prints a difference warning.
- [ ] `--fresh` on an existing path exits non-zero without modifying the file.
- [ ] Tests cover all three behaviors with temporary paths.
