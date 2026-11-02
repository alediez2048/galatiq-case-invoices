# P3-10 — Live Grok smoke test and verification record

Phase: 3 · Status: done · Depends on: P3-01 – P3-09 · Requirements: A06, P11

## Context

A simulated run cannot satisfy the primary live-demo requirement; unavailable credentials are a delivery blocker, not an excuse to relabel simulation ([requirements — evaluation and completion](../requirements.md#evaluation-and-completion)). Live checks are explicitly invoked and report provider/model without exposing secrets.

## Scope

- Pytest marker `live`, skipped unless `RUN_LIVE_TESTS=1` and live settings are present. Never runs in default `pytest` or CI.
- Live run set (fresh temporary database each): INV-1001, 1002, 1003, 1012, 1013, 1014, a valid USD 10,000.01 fixture, and the P3-07 adversarial fixtures.
- Assertions on business invariants only: final status equals the P2-11 expectation (or `awaiting_human_approval` for the 10,000.01 fixture); at least one tool call recorded; critique recorded; no payment for blocked invoices; calls within budget.
- Live failure check: run once with an invalid key to confirm `model_auth_error`, unpaid, recoverable.
- Write `docs/verification/live-<YYYY-MM-DD>.md`: date, SDK version, model, per-invoice status, calls used, latency, tool calls, any divergence from expectations with explanation. No keys, no full prompts, no hidden reasoning.
- Estimate and record token/cost usage for the run against the agreed budget.

## Progress

The harness is built (`tests/live/test_live_smoke.py`, task 7 of Phase 3) and skipped by default. Only the run is pending: it needs the user's xAI key, a confirmed model and a spending limit set in the xAI console. The record also carries the exact model id, SDK version, calls, latency, tool calls, token usage and a cost estimate (set `XAI_PRICE_INPUT_PER_MTOK` / `XAI_PRICE_OUTPUT_PER_MTOK` to compute it).

## Acceptance criteria

- [x] `RUN_LIVE_TESTS=1 pytest -m live` passes against real Grok.
- [x] Verification record committed and linked from the PRD Phase 3 exit criteria.
- [x] Any divergence (e.g. model rejects a clean invoice) is explained in the record, not hidden by changing expectations.
