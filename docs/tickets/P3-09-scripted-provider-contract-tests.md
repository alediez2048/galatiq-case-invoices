# P3-09 — Scripted fake provider and live-path contract tests

Phase: 3 · Status: todo · Depends on: P3-02 – P3-08 · Requirements: P10, A07

## Context

Default tests run offline with controlled reasoning responses; actual provider verification is separate and explicitly invoked ([techstack — dependency and verification policy](../techstack.md#dependency-and-verification-policy)). The live code path (adapter, tool loop, budget, repair, critique) must still be exercised without network access.

## Scope

- `tests/fakes/xai_client.py`: a fake implementing the subset of the SDK surface the adapter uses (`chat.create`, `append`, `sample`, `parse`, `tool_calls`). Driven by a script of steps: return parsed object, return tool calls, return malformed output, raise timeout/429/5xx/auth.
- Contract tests through `process_invoice(mode="live")` with the fake injected:
  - Happy path INV-1001 with a tool call to `lookup_inventory` → `paid_mock`.
  - Malformed output → repair → success.
  - Timeout → retry → success; timeout ×2 → `failed` recoverable.
  - Tool loop runaway → `model_tool_loop_exceeded`.
  - Budget exhaustion → `model_budget_exhausted`.
  - Unauthorized tool request → `tool_rejected`, run continues.
- Parity test: for every supplied fixture, live mode with a "reasonable" scripted fake yields the same final status as the P2-11 offline expectation.
- All tests run with the P1-10 network guard.

## Acceptance criteria

- [ ] Every model error code from P3-02 and P3-04 is produced by at least one test.
- [ ] Parity test covers all 20 supplied files.
- [ ] Suite needs no credentials and no network.
