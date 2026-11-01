# P3-01 — Live mode configuration and credentials

Phase: 3 · Status: todo · Depends on: P1-09, P1-03 · Requirements: A06, P11, P08

## Context

Live mode requires explicit configuration, credentials, and internet access. No hosted-model transmission begins merely by running the app, and credentials load only for live execution ([constraints — primary ambiguity](../contraints.md#primary-ambiguity-llm-integration-versus-offline-execution), [techstack — model integration](../techstack.md#model-integration-stays-replaceable-and-observable)).

## Scope

- `src/invoice_processing/settings.py`: live settings read only when `mode == "live"`:
  - `XAI_API_KEY` (required), `XAI_MODEL` (required, no hard-coded default; docs examples on 2026-11-01 use `grok-4.7`), `XAI_TIMEOUT_SECONDS` (default 30), `MODEL_CALL_BUDGET` (default 6).
  - Optional `.env` loading for local use; `.env.example` committed with a placeholder key and the model name verified in P3-10 (so an evaluator knows what to set), repeated in the README.
- `get_provider("live")` (P1-03) now builds the xAI adapter (P3-02) instead of failing; missing key or model → clear configuration error before any invoice record is created.
- CLI `--mode live` enabled; on start prints `Mode: live model (<model>) — invoice text will be sent to xAI`.
- `python -m invoice_processing.readiness`: reports which live settings are present (never their values) without calling the network unless `--ping` is passed.
- Redaction: settings object's `repr` masks the key; observability redaction test (P1-08) extended to cover it.

## Out of scope

The adapter itself (P3-02). Local-model support (deferred per constraints).

## Acceptance criteria

- [ ] With no environment variables, offline runs are unaffected and never import `xai_sdk`.
- [ ] `--mode live` without a key exits non-zero with a configuration message; no run row is created.
- [ ] The key never appears in logs, results, audit events, or exceptions (test with a sentinel value).
- [ ] `.env` is gitignored; `.env.example` contains no real values.
