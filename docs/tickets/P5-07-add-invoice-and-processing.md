# P5-07 — Add invoice and processing views

Phase: 5 · Status: todo · Depends on: P5-02, P5-05 · Requirements: P07, P11

## Context

[Mockup screens 2 and 3](../mockup.md#screen-2--add-an-invoice): drop zone with formats and limit; selected file; explicit mode explanation; Process disabled until checks pass with the reason shown; stage progress driven only by real events; no cancel or background controls; double submission prevented.

## Scope

- Add-invoice panel: drop zone + Browse, "PDF, TXT, CSV, JSON, XML · Up to 10 MiB", client-side pre-check of size and extension (server remains authoritative), selected file with Remove.
- Mode copy: offline — "Local checks and simulated agent decisions. No external model calls."; live — "Invoice content will be sent to the configured model provider. Payments remain simulated." Live is selectable only when readiness says it is configured; never enabled silently.
- "Eligible invoices up to USD 10,000 can auto-pay. No real money moves."
- Process button generates an idempotency key, posts once, and disables itself.
- Processing view: four stages (Extract details → Check inventory → Review → Pay) with complete/active/pending/failed/skipped symbols paired with text; messages from actual events, including "Checking an extraction issue — attempt 2 of 2" and "Checking the recommendation against policy"; "Payment has not been attempted." until a payment event exists. Opens the detail view on a terminal result.
- Live failure shows "Model request failed. Payment was not attempted." with Retry and "Run offline as a separate simulation".

## Acceptance criteria

- [ ] Selecting a file or sample never creates a run (asserted via API mock in tests).
- [ ] Double-clicking Process creates one run.
- [ ] Stage display for an offline 1001 run matches the persisted event sequence.
- [ ] Retry after a scripted live failure creates a linked run and shows its outcome.
