# P4-01 — Invoice versioning and review contracts

Phase: 4 · Status: todo · Depends on: P2-10, P0-04 · Requirements: P13, P08

## Context

Corrections create a new version without editing original bytes; old records remain immutable; correction and approval requests carry the version the reviewer saw ([system design — core data contracts](../systemsdesign.md#core-data-contracts), [persistence](../systemsdesign.md#persistence-and-transaction-boundaries)).

## Scope

- Pydantic contracts in `schemas.py`:
  - `Correction`: invoice ID, base version, field path (e.g. `line_items[2].unit_price`), old extracted value, new value, evidence location, reviewer, reason (required, non-empty), timestamp, resulting version.
  - `HumanReview`: invoice ID, validated version, action (`approve` | `decline`), reviewer, reason (required), timestamp, policy version.
  - `ReviewAction` enum and `AllowedActions` (which actions are valid for an invoice right now, and why others are not).
- `invoice_versions`: monotonically increasing version number per invoice, `parent_version`, `origin` (`source` | `correction`), and a `current_version` pointer on `invoices`.
- Immutability: SQLite triggers reject `UPDATE`/`DELETE` on `sources`, `invoice_versions`, `corrections`, `human_reviews`, `payments`, and `audit_events`.
- Reviewer identity is a free-text local name recorded for audit, explicitly not authentication ([constraints](../contraints.md#proposed-operational-bounds)).

## Acceptance criteria

- [ ] Attempting to update or delete a row in any immutable table raises.
- [ ] A correction with an empty or whitespace-only reason fails validation.
- [ ] Version numbers increase by one per correction and link to their parent.
- [ ] Schema version bumped; `init_schema` upgrades a Phase 3 database without data loss (test with a populated fixture DB).
