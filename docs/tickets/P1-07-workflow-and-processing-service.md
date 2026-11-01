# P1-07 — LangGraph workflow and shared processing service

Phase: 1 · Status: todo · Depends on: P1-06, P1-02 · Requirements: A07, P06

## Context

LangGraph coordinates the stages; a single processing service is the entry point for the CLI now and FastAPI in Phase 5 ([system design — architecture](../systemsdesign.md#architecture)).

## Scope

- Add `langgraph` to dependencies and refresh the lock (P0-01 workflow).
- `src/invoice_processing/workflow.py`: typed graph state (Pydantic or `TypedDict`); nodes ingestion → validation → approval → payment; conditional edges so `failed` exits from any stage and only `approved` reaches payment execution.
- `src/invoice_processing/service.py`: `process_invoice(path, mode, db_path, evaluation_date) -> ProcessingResult`:
  1. Intake and hash the source; if an identical source has a prior terminal outcome, return status `duplicate` with a reference to that outcome and receipt. No new payment.
  2. Otherwise start a run, invoke the graph, persist the terminal state, and return the result.
  3. Any unexpected exception → run `failed` with a concise error code; never leaves a partial payment.
- Processing is serialized (one invoice at a time) for this phase.

## Out of scope

Alternate formats and revisions under the same identity (Phase 2). Human-review resumption (Phase 4).

## Acceptance criteria

- [ ] `process_invoice` on INV-1001 offline returns `paid_mock` with a USD 5,000.00 receipt.
- [ ] Second call on the same file returns `duplicate` referencing the first receipt; payments table still has one row.
- [ ] An injected exception in the validation node yields `failed` and no payment.
- [ ] Graph structure test: the payment execution step is unreachable from any state other than `approved`.
