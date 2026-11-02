# P4-01 — Invoice versioning and review contracts

Phase: 4 · Status: done · Depends on: P2-10, P0-04 · Requirements: P13, P08

## Context

Corrections create a new version without editing original bytes; old records remain immutable; correction and approval requests carry the version the reviewer saw ([system design — core data contracts](../systemsdesign.md#core-data-contracts), [persistence](../systemsdesign.md#persistence-and-transaction-boundaries)).

## Scope

- Pydantic contracts in `schemas.py`:
  - `Correction`: invoice ID, base version, field path (e.g. `line_items[2].unit_price`), old extracted value, new value, evidence location, reviewer, reason (required, non-empty), timestamp, resulting version.
  - `HumanReview`: invoice ID, validated version, action (`approve` | `decline`), reviewer, reason (required), timestamp, policy version.
  - `ReviewAction` enum and `AllowedActions` (which actions are valid for an invoice right now, and why others are not).
- `invoice_versions`: monotonically increasing version number per invoice, `parent_version`, `origin` (`source` | `correction`), a mutable `version_status` column (`current` | `superseded`, set by P4-05), and a `current_version` pointer on `invoices`.
- Immutability: SQLite triggers reject `DELETE` on `sources`, `invoice_versions`, `corrections`, `human_reviews`, `payments`, and `audit_events`, and reject `UPDATE` on those tables except for `invoice_versions.version_status` (revised 2026-11-01 so P4-05 can mark versions superseded).
- Reviewer identity is a free-text local name recorded for audit, explicitly not authentication ([constraints](../contraints.md#proposed-operational-bounds)).

## Acceptance criteria

- [x] Attempting to delete a row in any immutable table, or update any column other than `invoice_versions.version_status`, raises; updating `version_status` succeeds. (`tests/test_immutability.py::test_delete_rejected`, `::test_update_rejected`, `::test_every_other_column_of_an_exception_table_is_guarded`, `::test_insert_or_replace_rejected`, `::test_version_status_current_to_superseded_allowed`)
- [x] A correction with an empty or whitespace-only reason fails validation. (`tests/test_review_contracts.py::test_blank_reason_rejected`, `::test_human_review_reason_and_reviewer_required`)
- [x] Version numbers increase by one per correction and link to their parent. (`tests/test_ledger.py::test_correction_versions_increment_and_link_parent`, `::test_correction_version_inserted_even_with_equal_semantic_hash`)
- [x] Schema version bumped; `init_schema` upgrades a Phase 3 database without data loss (test with a populated fixture DB). (`tests/test_migration.py::test_previous_version_db_upgrades_without_data_loss`, `::test_migrated_schema_matches_a_fresh_one`, `::test_failed_migration_leaves_the_previous_version`)

## As built (2026-11-02)

- Schema 7, migrated in place from schema 6 only (`tests/fixtures/review/previous_schema.sql`); older databases are still refused.
- Immutable tables also include `findings` and `decisions`. Besides `version_status` (`current` → `superseded` only), two narrow updates stay allowed: `sources.extracted_text` from `NULL` to a value, and `payments.run_id` alone while the old paying run is `failed` (the Phase 3 crash replay, audit event `payment_run_repointed`). `INSERT OR REPLACE` is refused too.
- Version origins are `source` | `correction`; field paths use `lines[N]` (for example `lines[0].unit_price`), not `line_items[N]`. Runs record `trigger` (`submission` | `correction` | `human_review` | `corrected_submission`) and `review_of`.
- Carry-over from P2-10 pinned by tests: a semantic-hash match returns the first version's payload and does not move `current_version` (`tests/test_ledger.py::test_record_version_hash_match_returns_first_payload_and_keeps_current`).
