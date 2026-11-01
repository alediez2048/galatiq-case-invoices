# P3-04 — Bounded agent loops and per-invoice model budget

Phase: 3 · Status: todo · Depends on: P3-02, P3-03, P1-07 · Requirements: P09

## Context

[Constraints — operational bounds](../contraints.md#proposed-operational-bounds): one extraction-repair retry, one approval revision after critique, no unbounded conversations; 30 s timeout; ≤ 2 transport attempts; a total model-call budget per invoice enforced in orchestration, initially six calls including retries.

## Scope

- Budget counter in graph state, decremented for every model request **including** transport retries and tool-loop turns; checked before each request, not after.
- Tool loop per agent step: at most 3 model turns (request → tool calls → follow-up), configurable; exceeding it → `model_tool_loop_exceeded`.
- Budget exhausted → run `failed` with `model_budget_exhausted`; invoice unpaid; recoverable via P3-08.
- Expected call plan for a normal run, documented in the module: extraction assist (0–2, only when needed), recommendation (1), critique (1), revision (0–1). Total ≤ 6 in the normal case.
- Budget and per-call usage reported in the final `ProcessingResult` (`model_calls_used`, `model_calls_budget`).

## Acceptance criteria

- [ ] With a fake provider that always requests another tool call, the run stops at the tool-loop cap with no payment.
- [ ] With budget set to 2, a run needing recommendation + critique + revision fails with `model_budget_exhausted` before the third call.
- [ ] Transport retries count against the budget (asserted with a fake that times out once).
- [ ] Offline mode reports `model_calls_used = 0`.
