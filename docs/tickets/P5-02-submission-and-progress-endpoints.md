# P5-02 — Submission and processing-progress endpoints

Phase: 5 · Status: todo · Depends on: P5-01, P2-01 · Requirements: P07, P12

## Context

One invoice per submission. Selecting a file never starts processing. Stages update only when actual workflow events arrive. Page refreshes and repeated requests must never initiate processing or payment ([mockup — screens 2 and 3](../mockup.md#screen-2--add-an-invoice)).

## Scope

- `GET /api/samples`: list files in `data/invoices/` with a descriptive label per sample ("Clean invoice", "Stock mismatch", "Messy formatting", "Conflicting totals", "Unsupported currency", …) and invoice number. Labels describe inputs, never claim outcomes.
- `POST /api/runs` with either a multipart upload or `{sample: name}` (`name` must be a bare basename present in `data/invoices/`; anything else is 422), plus required `mode` (`offline` | `live`), optional `evaluation_date` (defaults to a workspace setting, itself defaulting to today), and a client-generated `Idempotency-Key` header. The same key returns the existing run instead of starting another. Duplicate submissions get a normal run (status `duplicate`, P1-07), so polling works the same.
  - Uploads stream to the gitignored `uploads/` directory with the 10 MiB cap enforced while streaming; filenames sanitized; stored by content hash.
  - Live mode refused with a readiness error if not configured.
  - Returns `202` with `run_id`; processing runs in a background worker under the P5-01 lock.
- `GET /api/runs/{run_id}`: status, current stage, completed stage events (from audit events), terminal result when done. Polled by the client (recommended 500 ms) rather than SSE, for simplicity.
- `POST /api/runs/{run_id}/retry`: wraps P3-08 retry for recoverable failures.

## Acceptance criteria

- [ ] Posting twice with the same idempotency key creates one run.
- [ ] An 11 MiB upload is rejected with 413 before being fully written.
- [ ] A path-traversal filename (`../../x.txt`) is stored safely under `uploads/`.
- [ ] Progress events returned are exactly the persisted audit events, in order.
