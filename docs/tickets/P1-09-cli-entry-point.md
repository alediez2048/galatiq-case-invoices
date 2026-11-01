# P1-09 — CLI entry point

Phase: 1 · Status: done · Depends on: P1-07, P1-08 · Requirements: A09

> Implemented with default mode `offline` pending user confirmation of the open decision below.

## Context

The assignment requires `python main.py --invoice_path=data/invoices/invoice1.txt`. The design proposes extra options for mode, database path, output path, and evaluation date, with final names fixed during implementation ([system design — interface](../systemsdesign.md#interface)).

## Scope

- `main.py` at the repo root using `argparse`, delegating to `service.process_invoice`. No business logic in the CLI.
- Options (names fixed here):
  - `--invoice_path` (required; also accept `--invoice-path`).
  - `--mode {offline,live}`.
  - `--db` (default `inventory.db`).
  - `--output` (default stdout).
  - `--events` (default `output/events.jsonl`).
  - `--evaluation-date YYYY-MM-DD` (default today, recorded in the result).
- Exit codes: `0` for any completed business outcome (including `rejected`, `duplicate`, waiting states); non-zero for `failed` and usage errors.
- Missing database or uninitialized schema → create it and run the idempotent seed (P0-05 never resets existing data), printing `Initialized <path> and seeded inventory` to stderr. This keeps the assignment's bare command working on a fresh clone and matches the API's startup behavior (P5-01). (Revised 2026-11-01; earlier wording refused to run.)
- Update `docs/development.md` with run examples.

## Decision needed

**Default when `--mode` is omitted.** The assignment command has no mode flag, so it must still run. Recommendation: default to `offline`, print `Mode: offline simulation` prominently, and require `--mode live` for Grok. This keeps the bare command network-free, consistent with "no hosted-model transmission merely by opening the app." Confirm before implementing.

## Acceptance criteria

- [ ] `python main.py --invoice_path=data/invoices/invoice_1001.txt` runs after documented setup and prints a `paid_mock` result.
- [ ] `--mode live` fails with a clear "not available yet" message and exit code ≠ 0; invoice remains unpaid.
- [ ] Running against a missing database creates and seeds it, prints the notice, and completes the run; a second run prints no notice.
- [ ] `--help` documents every option.
