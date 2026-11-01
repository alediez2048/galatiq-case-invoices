# P1-08 — Structured logging and result output

Phase: 1 · Status: todo · Depends on: P0-01, P0-03 · Requirements: A09, P08

## Context

The assignment requires structured logs and results. The design calls for JSONL events with stage, run ID, source identity, status, duration, mode, and concise codes, plus a final JSON result kept separate from human-readable diagnostics ([system design — failure handling and observability](../systemsdesign.md#failure-handling-and-observability)).

## Scope

`src/invoice_processing/observability.py`:

- JSON formatter for Python `logging`; one event per line with `ts`, `run_id`, `stage`, `event`, `status`, `mode`, `source_hash`, `duration_ms`, `codes`.
- Stage timing helper (context manager) used by agent nodes.
- Redaction: never log API keys, environment variables, full invoice text, or model reasoning. Add a test that a value named like a key is not emitted.
- `write_result(result, path | stdout)`: final `ProcessingResult` as JSON, money as strings.
- Stream separation: JSONL events to a file (default `output/events.jsonl`) or stderr; final result JSON to stdout or `--output`; human-readable summary to stderr.

## Out of scope

Metrics dashboards, external observability services.

## Acceptance criteria

- [ ] Every line of the events file parses as JSON and contains `run_id` and `stage`.
- [ ] stdout contains only the final result JSON, so `python main.py ... | jq .status` works.
- [ ] Redaction test passes.
- [ ] Logs and results are written under gitignored paths.
