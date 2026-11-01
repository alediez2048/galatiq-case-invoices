# P6-03 — Demo setup and evaluator walkthrough

Phase: 6 · Status: todo · Depends on: P5-10, P3-10 · Requirements: A10, P11

## Context

[Mockup — suggested evaluator walkthrough](../mockup.md#suggested-evaluator-walkthrough) lists 11 steps, from live 1001 through high-value approval, correction, live failure, and the overview. Use fresh, explicitly initialized demo data; never silently reset the user's ledger. Use a separate demo database when independent offline and live demos need separate mock receipts ([constraints](../contraints.md#security-and-trust-boundaries)).

## Scope

- `scripts/demo_setup.py --db demo-live.db` (and `demo-offline.db`): creates a fresh seeded database; refuses an existing path; copies the review fixtures needed for steps 8–9 into a demo inputs folder.
- `scripts/start_demo.sh` (or documented commands) starting FastAPI and the built frontend against a chosen demo DB.
- `docs/demo.md`: the 11 steps with exact actions, the expected outcome per step, and what to point out (evidence, critique, no second payment, stale approval refusal, explicit retry, unique vs run counts).
- Rehearse the walkthrough in both modes; record any step that diverges and fix or document it.
- Optional: short screen recording or screenshots linked from the README.

## Acceptance criteria

- [ ] Walkthrough completes end to end in live mode and in offline mode on fresh demo databases.
- [ ] Demo setup never modifies an existing database.
- [ ] Every step in `docs/demo.md` matches observed behavior on the rehearsal date.
