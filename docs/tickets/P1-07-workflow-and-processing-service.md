# P1-07 — LangGraph workflow and shared processing service

Phase: 1 · Status: done · Depends on: P1-06, P1-02 · Requirements: A07, P06

## Context

LangGraph coordinates the stages; a single processing service is the entry point for the CLI now and FastAPI in Phase 5 ([system design — architecture](../systemsdesign.md#architecture)).

## Scope

- Add `langgraph` to dependencies and refresh the lock (P0-01 workflow).
- `src/invoice_processing/workflow.py`: typed graph state (Pydantic or `TypedDict`); nodes ingestion → validation → approval → payment; conditional edges so `failed` exits from any stage and only `approved` reaches payment execution.
- `src/invoice_processing/service.py`: `process_invoice(path, mode, db_path, evaluation_date) -> ProcessingResult`:
  1. Intake and hash the source; **always start a run** (only pre-intake usage errors such as a bad path skip run creation). If an identical source already has a prior *business* outcome (`paid_mock`, `rejected`, `needs_review`, `awaiting_human_approval`), finish this run as `duplicate` with `prior_run_id` and any prior receipt; the graph is not invoked and no payment occurs. A prior `failed` run is **not** a duplicate. Runs linked via `retry_of` (P3-08) or `mode_switch_of` are exempt from duplicate detection; payment uniqueness still applies at pay time. (Revised 2026-11-01 from plan review.)
  2. Otherwise invoke the graph, persist the terminal state, and return the result.
  3. Any unexpected exception → run `failed` with a concise error code; never leaves a partial payment.
  4. On startup, mark any non-terminal run older than the current process as `failed` with error code `interrupted`, so a crash after payment commit but before `finish_run` leaves a retryable record.
- Graph entry points: `start="ingestion"` (default) and `start="validation"` with a given invoice version, used by corrections in P4-02.
- Run/invoice status transition table lives in `workflow.py` as data and is enforced by `update_run_status`; a `duplicate` run never changes `invoices.status`; a blocked revision never moves `invoices.current_version` off a paid version.
- Processing is serialized (one invoice at a time) for this phase.

## Out of scope

Alternate formats and revisions under the same identity (Phase 2). Human-review resumption (Phase 4).

## Acceptance criteria

- [ ] `process_invoice` on INV-1001 offline returns `paid_mock` with a USD 5,000.00 receipt.
- [ ] Second call on the same file creates a second run row with status `duplicate` referencing the first run and receipt; payments table still has one row; `invoices.status` is still `paid_mock`.
- [ ] A run that failed, then the same file again → a normal new run (not `duplicate`).
- [ ] Transition-table test: every illegal transition (e.g. `paid_mock` → anything, `duplicate` → `paid_mock`) raises.
- [ ] An injected exception in the validation node yields `failed` and no payment.
- [ ] Graph structure test: the payment execution step is unreachable from any state other than `approved`.
