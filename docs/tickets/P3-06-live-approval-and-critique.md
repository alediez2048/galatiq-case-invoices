# P3-06 — Live approval recommendation and critique loop

Phase: 3 · Status: done · Depends on: P3-02, P3-03, P3-04, P1-04 · Requirements: A04, A07, P11

## Context

The approval agent proposes approve/reject/review with evidence; a critique challenges omissions and unsupported conclusions; one revised recommendation is allowed; then the independent deterministic gate (P1-04) decides. Store short summaries and cited evidence, never hidden reasoning ([system design — processing sequence](../systemsdesign.md#processing-sequence)).

## Scope

- Recommendation call: inputs are the normalized invoice, all findings with codes, the policy summary (blockers, USD 10,000 threshold, currency rule), and allowed tools. Output: decision, reasons each citing finding codes or tool results, and a ≤ 300-character summary.
- Critique call: a separate prompt/role that receives the recommendation and may call tools (e.g. `lookup_inventory`, `recompute_totals`) to check it. Output: `agrees` boolean, issues found (uncited blocker, unsupported claim, missed high-value scrutiny), optional revised decision.
- Deterministic critique checks run alongside the model's: every blocker must be cited by the final recommendation; high-value invoices must mention the threshold. Missing citations are recorded as critique issues even if the model missed them.
- If the critique disagrees, one revision call; no further loops.
- Persist: initial recommendation, critique summary and issues, revised recommendation (if any), gate result, provider/model, policy version, tool calls used.
- Add threshold-boundary fixtures `tests/fixtures/threshold/valid_10000_00.json` and `valid_10000_01.json` (USD, in-stock items, consistent arithmetic). Phase 4 reuses them for the human-approval flow.
- Prompts live in versioned files under `reasoning/prompts/`; the prompt version is recorded with each decision.

## Acceptance criteria

- [ ] Fake provider recommending approve on INV-1002 → critique issue `uncited_blocker`; gate result `rejected` regardless.
- [ ] Fake provider recommending reject on clean INV-1001 → recorded; gate result `awaiting_human_approval` with finding `model_disagreement` (per P1-04); a human approve then pays, a decline rejects.
- [ ] A clean otherwise-valid USD 10,000.01 fixture → critique confirms threshold scrutiny; gate → `awaiting_human_approval`.
- [ ] Exactly one critique and at most one revision per run (asserted with call counts).
