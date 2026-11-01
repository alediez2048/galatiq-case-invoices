# P1-06 — Ingestion, validation, approval, and payment agent nodes

Phase: 1 · Status: todo · Depends on: P1-01, P1-03, P1-04, P1-05, P0-06, P0-07, P0-08 · Requirements: A04, A07

## Context

[System design — agent responsibilities](../systemsdesign.md#agent-responsibilities-and-tools) defines four agents with separate permissions. In Phase 1 they run offline; the payment agent is deterministic by design.

## Scope

`src/invoice_processing/agents/`, one module per agent, each a function `(state) -> state update`:

- `ingestion.py`: calls intake, TXT parser, and normalizer (P1-01); sets status `extracted`; unrecoverable parse error → `failed`.
- `validation.py`: runs P0-06, P0-07, P0-08 checks against the inventory; sets status `validated`. Read-only inventory access.
- `approval.py`: recommendation → critique → at most one revised recommendation via the provider (P1-03), then the policy gate (P1-04). Records initial recommendation, critique summary, final decision, policy version, mode.
- `payment.py`: on `approved`, calls `pay` (P1-05) → `paid_mock`; on `rejected`, records rejection reasons; `needs_review` and `awaiting_human_approval` are persisted waiting states with no payment.
- Each node appends audit events via P1-02 and never calls tools outside its permitted list.

## Out of scope

Extraction repair retry, live tool calls (Phase 3).

## Acceptance criteria

- [ ] Each node is unit-tested in isolation with a constructed state.
- [ ] The approval node records exactly one critique and at most one revision.
- [ ] The validation node cannot write to `inventory` (assert stock unchanged).
- [ ] No node other than `payment.py` imports `payments.pay`.
