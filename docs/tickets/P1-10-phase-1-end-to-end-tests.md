# P1-10 — Phase 1 end-to-end and offline-network tests

Phase: 1 · Status: todo · Depends on: P1-09 · Requirements: A08, P10

## Context

Phase 1 exit criteria: INV-1001 yields `paid_mock` with a USD 5,000.00 receipt; rerunning does not pay twice; offline mode makes no network calls ([PRD — Phase 1](../PRD.md#phase-1--walking-skeleton-offline-one-invoice)).

## Scope

- Pytest fixture that blocks network access (patch `socket.socket.connect` and `socket.create_connection` to raise) and is applied to all default tests.
- End-to-end test via subprocess: seed a temp database, run `main.py` on INV-1001, parse stdout JSON.
- Rerun test: second invocation returns `duplicate`; payments table has one row.
- Restart test: run, discard the process, run again with the same database; still one payment.
- Failure test: corrupt copy of the TXT (invalid UTF-8) yields `failed`, non-zero exit, no payment.
- Audit test: the run's audit events cover every stage in order and include source hash, mode, policy version, and payment result.

## Acceptance criteria

- [ ] All tests pass with the network guard active.
- [ ] `pytest` from a clean clone (after install and seed) runs in under 30 seconds.
- [ ] Tests never touch the repo-root `inventory.db`.
- [ ] Phase 1 exit criteria in the PRD are checked off with a link to the passing test names.
