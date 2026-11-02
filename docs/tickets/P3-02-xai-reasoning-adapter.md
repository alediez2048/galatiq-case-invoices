# P3-02 — xAI reasoning adapter

Phase: 3 · Status: done · Depends on: P3-01, P1-03 · Requirements: A06, A07, P09

## Context

The assignment's `from xai import Grok` snippet is illustrative; the techstack requires confirming the current SDK from official docs. As read on 2026-11-01 ([function calling](https://docs.x.ai/docs/guides/function-calling), [structured outputs](https://docs.x.ai/docs/guides/structured-outputs)):

- `from xai_sdk import Client`; `client.chat.create(model=..., tools=[...])`; `chat.append(...)`; `chat.sample()`.
- Tools: `tool(name=, description=, parameters=<JSON schema>)` from `xai_sdk.chat`; tool calls read from `response.tool_calls`, results returned with `tool_result(...)`. Parameter schema root must be an object.
- Structured output: `response, obj = chat.parse(PydanticModel)`; combinable with client-side tools on supported Grok 4 models. `additionalProperties` defaults to `false`; some constructs (`not`, `if/then/else`, multi-subschema `allOf`) are best-effort only.

Re-verify these against the installed SDK version when implementing; record the version used.

## Scope

- Add the xAI SDK dependency (confirm the pip package name, expected `xai-sdk`) and refresh the lock.
- `reasoning/xai.py`: `XaiProvider` implementing `ReasoningProvider` (`recommend`, `critique`, `assist_extraction`).
  - Uses `chat.parse` with the Pydantic output types; then re-validates locally with `model_validate` regardless of server-side enforcement.
  - Keep output schemas inside the strictly-enforced subset (no `not`, `if/then/else`, multi-`allOf`); add a unit test that walks each schema and fails on unsupported keywords.
  - Request timeout from settings; at most two transport attempts, only for transient errors (timeout, connection reset, 429, 5xx). Auth, 4xx schema errors, and invalid output are not retried at transport level.
  - Error classification into stable codes: `model_auth_error`, `model_rate_limited`, `model_timeout`, `model_unavailable`, `model_output_invalid`, `model_refused`.
  - Records provider, model, SDK version, latency, and token usage (if exposed) per call into audit events; never the raw prompt with secrets or any hidden reasoning.
- The adapter receives a client factory so tests can inject a fake (P3-09).

## Out of scope

Tool definitions and dispatch (P3-03). Call budget across a run (P3-04).

## Acceptance criteria

- [ ] With a fake client returning a valid parsed object, `recommend` returns a typed `Recommendation` labeled `mode=live`.
- [ ] A fake transient timeout followed by success makes exactly two attempts; a third failure path raises `model_timeout`.
- [ ] Invalid JSON or schema-violating output raises `model_output_invalid` after local validation.
- [ ] Schema-subset test passes for every output type.
