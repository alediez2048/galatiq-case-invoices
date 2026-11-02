# P3-04 — Bounded agent loops and per-invoice model budget

Phase: 3 · Status: done · Depends on: P3-02, P3-03, P1-07 · Requirements: P09

## Context

[Constraints — operational bounds](../contraints.md#proposed-operational-bounds): one extraction-repair retry, one approval revision after critique, no unbounded conversations; 30 s timeout; ≤ 2 transport attempts; a total model-call budget per invoice enforced in orchestration, initially six calls including retries.

## Scope

- Budget counter in graph state counts **top-level agent steps** (one extraction assist, one recommendation, one critique, one revision each count once, and a transport retry of a step counts again); tool-loop follow-up turns inside a step do not count against the budget. Checked before each step, not after. (Revised 2026-11-01: counting tool turns made recommendation + critique alone exhaust the budget.)
- Tool loop per agent step: at most 3 model turns (request → tool calls → follow-up), configurable, tracked separately; exceeding it → `model_tool_loop_exceeded`. A step with tools makes at most tool cap + 2 requests (the first sample, one sample per tool turn, then the structured-output parse), so the worst case per invoice is budget × (tool cap + 2) transport requests (6 × 5 = 30 with the defaults), documented in `reasoning/xai.py`. (Revised 2026-11-01: the earlier "budget × (1 + tool cap)" omitted the final parse request.)
- Budget exhausted → run `failed` with `model_budget_exhausted`; invoice unpaid; recoverable via P3-08.
- Expected call plan for a normal run, documented in the module: extraction assist (0–2, only when needed), recommendation (1), critique (1), revision (0–1). Total ≤ 6 in the normal case.
- Budget and per-call usage reported in the final `ProcessingResult` (`model_calls_used`, `model_calls_budget`).

## Acceptance criteria

- [ ] With a fake provider that always requests another tool call, the run stops at the tool-loop cap with no payment.
- [ ] With budget set to 2, a run needing recommendation + critique + revision fails with `model_budget_exhausted` before the third call.
- [ ] Transport retries count against the budget (asserted with a fake that times out once); tool follow-up turns do not (a recommendation using 3 tool turns consumes one budget unit).
- [ ] Offline mode reports `model_calls_used = 0`.
