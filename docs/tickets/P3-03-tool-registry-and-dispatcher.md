# P3-03 — Whitelisted tool registry and dispatcher

Phase: 3 · Status: done · Depends on: P1-06, P0-08, P1-02 · Requirements: A07

## Context

Reasoning agents use whitelisted function calls; tool requests execute through an application dispatcher that validates arguments and authorization ([system design — agent responsibilities](../systemsdesign.md#agent-responsibilities-and-tools)). The payment agent stays deterministic; no model can reach payment.

## Scope

- `src/invoice_processing/tools.py`: each tool = name, description, Pydantic argument model (also used to produce the xAI JSON schema), handler, and the set of agents allowed to call it.

| Tool | Allowed agents | Behavior |
| --- | --- | --- |
| `lookup_inventory(items)` | validation, approval | Read-only stock for canonical items (P0-04 `get_stock`). |
| `recompute_totals()` | validation, approval | Reruns P0-07 on the current normalized invoice; returns computed values and findings. |
| `get_findings(severity?)` | approval | Returns persisted findings for this run. |
| `lookup_prior_invoice()` | validation, approval | Prior versions, outcomes, and payment status for this identity (P2-10). |
| `get_source_excerpt(location)` | ingestion, approval | Returns a bounded snippet of the current source by evidence location. |
| `list_item_aliases()` | ingestion | Known canonical items and documented alias rules (P2-08). |

- Tools act only on the current run's invoice; no tool accepts a file path, SQL, or arbitrary item list beyond 200 entries.
- Dispatcher: unknown tool, unauthorized agent, or invalid arguments → structured error result returned to the model (`{"error": "tool_rejected", "reason": ...}`), audited as a `tool_call` event with `ok=false` and the reason (there is no separate `tool_rejected` event); never raises into the graph.
- Every call and result is persisted (tool, agent, validated args, result summary, duration).
- No payment, write, or policy-changing tool exists; a test asserts the registry contains none.

## Acceptance criteria

- [ ] Approval agent calling `list_item_aliases` → `tool_rejected` (unauthorized).
- [ ] `lookup_inventory` with a non-list argument → `tool_rejected` (invalid args).
- [ ] Inventory stock is unchanged after any sequence of tool calls.
- [ ] Generated JSON schemas pass the P3-02 subset check and have object roots.
