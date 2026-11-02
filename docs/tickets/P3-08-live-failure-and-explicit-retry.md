# P3-08 — Live failure handling and explicit retry

Phase: 3 · Status: done · Depends on: P3-02, P3-04, P1-07 · Requirements: P15, P06

## Context

Failed live reasoning leaves the invoice unpaid with an actionable error and explicit retry. Offline simulation requires a separate selection and run and never silently replaces live processing or inherits live approval ([decisions — round 2](../decisions.md#round-2--implementation-consequences)). Mockup copy: "Model request failed. Payment was not attempted."

## Scope

- Any model error code from P3-02/P3-04 → run `failed` with that code, `recoverable = true`, and the stage reached. Deterministic findings already computed are kept.
- `service.retry_run(run_id) -> ProcessingResult`: allowed for recoverable failed runs, including `interrupted` ones from the P1-07 startup sweep; creates a new run in the **same mode** linked to the original (`retry_of`), which exempts it from duplicate detection; reprocesses from the stored source; payment uniqueness still applies, so a retry after a committed payment reveals the existing receipt rather than paying again.
- A user-requested run of the same source in the other mode is recorded with `mode_switch_of` pointing at the latest run of that source, also exempt from duplicate detection, never inheriting the earlier recommendation or approval.
- CLI: `python main.py --retry RUN_ID`. Prints the original failure and the new outcome.
- Switching modes: running the same invoice with `--mode offline` creates a new run labeled offline; it never reuses live recommendations, and any payment it makes still counts against the same business identity.
- Failure result includes a user message, the error code, and the next actions (`retry`, or `run offline as a separate simulation`).

## Acceptance criteria

- [ ] Fake provider raising `model_unavailable` → `failed`, recoverable, no payment, message matches the mockup copy.
- [ ] `--retry` on that run with a now-working fake → new linked run, `paid_mock` for INV-1001, one payment total.
- [ ] `--retry` on a non-failed or non-recoverable run is refused.
- [ ] An offline run after a failed live run is labeled offline and shows no live decision data.
- [ ] No code path converts a live failure into an offline result (grep-style test on the provider factory plus behavior test).
