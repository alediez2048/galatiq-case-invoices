# P1-03 — Reasoning interface and offline simulator

Phase: 1 · Status: done · Depends on: P0-03 · Requirements: A07, A08

## Context

Live Grok arrives in Phase 3, but the interface must exist now so agents and graph contracts are shared between modes. Offline mode must not initialize any model SDK or touch the network, and must be visibly labeled as simulation ([constraints — primary ambiguity](../contraints.md#primary-ambiguity-llm-integration-versus-offline-execution)).

## Scope

- `src/invoice_processing/reasoning/base.py`: a `ReasoningProvider` protocol with typed methods:
  - `recommend(invoice, findings, policy) -> Recommendation` (approve / reject / review, reasons citing finding codes).
  - `critique(invoice, findings, recommendation, policy) -> Critique` (agrees or lists omissions/unsupported claims, optional revised recommendation).
  - `assist_extraction(...)` stub signature only; unused until Phase 2/3.
  - Each response carries `mode`, `provider`, `model` (or `simulated`).
- `reasoning/offline.py`: `OfflineSimulator` producing deterministic responses from findings and policy. Recommendation = reject if any blocker, review if unresolved warnings require it, else approve. Critique checks the recommendation cites every blocker and flags the high-value threshold when applicable.
- `reasoning/__init__.py`: `get_provider(mode)`; `live` raises a clear "not available until Phase 3" error. No silent fallback.
- Every simulated output is labeled `offline simulation` in its summary text.

## Out of scope

xAI adapter, tool calling, retries, model budgets (Phase 3).

## Acceptance criteria

- [ ] Simulator outputs validate against their Pydantic types.
- [ ] Same inputs always give identical outputs.
- [ ] Importing and using the offline provider does not import any model SDK.
- [ ] `get_provider("live")` fails explicitly; nothing falls back to offline.
