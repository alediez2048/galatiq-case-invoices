# P1-02 — Ledger writes and audit events

Phase: 1 · Status: done · Depends on: P0-04, P0-03 · Requirements: P05 (exact file), P06, P08

## Context

P0-04 created the tables; nothing writes to them yet. Every state transition must write an audit event, and identical files must be recognized on rerun ([system design — persistence](../systemsdesign.md#persistence-and-transaction-boundaries)).

## Scope

Repository functions in `storage.py` (or `ledger.py`), all parameterized SQL:

- `record_source(source)`: insert or return the existing row for a content hash; report whether it already existed.
- `upsert_invoice(identity)`: business identity = canonical vendor key + invoice number key. When either is missing (INV-1009 has an empty vendor), use the **provisional identity** `vendor_key = "pending"`, `invoice_number_key = "pending:<source content hash>"`; provisional identities are never payable (the gate's required-field blockers guarantee it) and are replaced only through the identity-correction path in P4-03. Both key columns stay `NOT NULL` so the uniqueness constraint always applies. (Added 2026-11-01 from plan review.)
- `record_version(invoice_id, normalized, semantic_hash)`: semantic hash over payable content only (vendor key, number key, currency, due date, canonical lines sorted by item/quantity/unit price so line order does not matter, final total), excluding filename, layout, stated subtotal/tax lines, notes, and terms text.
- `start_run(mode, source_id) -> run_id` (UUID4), `update_run_status(run_id, status)`, `finish_run(run_id, status, error=None)`.
- `record_findings(run_id, version_id, findings)`, `record_decision(run_id, decision)`.
- `append_audit_event(run_id, stage, event, payload)`: ordered, UTC timestamps; payload never contains secrets or raw model reasoning.
- `find_prior_outcome(source_hash)`: latest terminal run and any payment for an identical source.

## Out of scope

Revision conflicts and alternate-format matching (Phase 2). Corrections and human reviews (Phase 4). Payment writes (P1-05).

## Acceptance criteria

- [ ] Recording the same source twice returns one row and flags the second as existing.
- [ ] Semantic hash is identical for two drafts differing only in filename, whitespace, or line order, and different when any line quantity changes.
- [ ] A draft with no vendor gets a provisional identity; two such drafts from different sources get different identities.
- [ ] Run status transitions and audit events are persisted in order and readable back.
- [ ] Tests use temporary databases.
