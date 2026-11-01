# P0-04 — SQLite schema and storage module

Phase: 0 · Status: done · Depends on: P0-01 · Requirements: A03, P05 (constraint only), P08 (tables only)

## Context

One SQLite database (default `inventory.db`) is the local source of truth for inventory and the processing ledger. [System design — persistence](../systemsdesign.md#persistence-and-transaction-boundaries) lists eleven logical tables. Payment uniqueness must be enforced by a database constraint, not just application code.

## Scope

- `src/invoice_processing/storage.py`:
  - `connect(path)` helper: enables foreign keys, sets WAL journal mode, returns a connection with row factory.
  - `init_schema(conn)`: creates tables if absent and records a schema version (`PRAGMA user_version`). Running it twice is a no-op.
  - Transaction helper (`with write_transaction(conn):` using `BEGIN IMMEDIATE`) for later payment use.
- Tables (columns may grow in later phases; keep each to what the design names):
  - `inventory(item TEXT PRIMARY KEY, stock INTEGER NOT NULL CHECK (stock >= 0))`
  - `sources`, `invoices`, `invoice_versions`, `runs`, `findings`, `decisions`, `corrections`, `human_reviews`, `payments`, `audit_events`.
  - `invoices` unique on (`vendor_key`, `invoice_number`).
  - `payments` unique on the business invoice identity; amount stored as decimal string plus currency.
  - `sources` unique on content hash.
- Read-only inventory lookup function `get_stock(conn, items) -> dict[str, int | None]` using parameterized SQL.
- Money columns are `TEXT` holding decimal strings; timestamps are ISO-8601 UTC `TEXT`.

## Out of scope

Seed data (P0-05). Writing runs, findings, or payments (Phases 1–2). Migrations framework; a version check that refuses unknown future versions is enough.

## Acceptance criteria

- [ ] `init_schema` on a temporary database creates all eleven tables; second call changes nothing.
- [ ] Inserting two `payments` rows for the same invoice identity fails with an integrity error.
- [ ] `get_stock` returns `None` for unknown items and never interpolates item names into SQL.
- [ ] Tests use temporary databases only; no test touches `inventory.db` in the repo root.
