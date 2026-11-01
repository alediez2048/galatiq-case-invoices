# P4-06 — Review CLI

Phase: 4 · Status: todo · Depends on: P4-02 – P4-05 · Requirements: A09, P13, P14

## Context

The review workflow must work end to end through the shared service before any UI (PRD Phase 4 goal). A CLI makes it demonstrable and testable now and keeps `main.py --invoice_path=...` unchanged.

## Scope

- `python -m invoice_processing.review_cli` with subcommands:
  - `queue`: grouped queue (P4-05).
  - `show INVOICE_ID`: current version, findings, decision, allowed actions, history.
  - `correct INVOICE_ID --version N --field F --value V --evidence LOC --reason R --reviewer NAME`.
  - `approve` / `decline INVOICE_ID --version N --reason R --reviewer NAME`.
  - `submit-corrected INVOICE_ID --invoice_path P --reason R --reviewer NAME`.
- Same output conventions as P1-08: result JSON on stdout, human summary and events elsewhere.
- No business logic in the CLI; every command calls `review.py`.

## Acceptance criteria

- [ ] Each subcommand has a subprocess test.
- [ ] Missing `--reason` or `--version` is a usage error.
- [ ] `--help` documents every subcommand; usage examples added to `docs/development.md`.
