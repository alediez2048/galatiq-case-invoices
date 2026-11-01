# P6-01 — Robustness test campaign

Phase: 6 · Status: todo · Depends on: P2-11, P3-09, P4-07, P5-10 · Requirements: P09, P10

## Context

[System design — verification order step 6](../systemsdesign.md#verification-and-delivery-order): run the whole corpus, error injection, malformed input, payment replay, threshold-boundary, and offline-network tests; document results and limitations. Use generated variations, not filename-specific decisions.

## Scope

- **Whole corpus, one persistent ledger:** process all 20 files in a fixed order, then again in reverse order on a fresh DB; assert one payment per identity and identical final outcomes per identity.
- **Error injection:** force an exception at each stage (intake, each parser, normalization, validation, approval, gate, payment before commit, payment after commit) and assert `failed` or the correct persisted outcome with no extra payment; for the post-commit case, retry reveals the existing payment instead of paying again.
- **Generated variations** (seeded, reproducible) of supplied fixtures: shuffled line order, whitespace/case noise, renamed files, alternate label spellings from the P2-02 dictionary, random quantity bumps across stock limits. Assert outcomes follow the rules, not the filenames.
- **Malformed input:** truncated files, binary junk with valid extensions, deeply nested JSON, huge single lines, mixed encodings.
- **Payment replay:** repeated CLI runs, API retries with and without idempotency keys, concurrent approvals, process kill between gate and payment.
- **Threshold boundaries:** 9,999.99 / 10,000.00 / 10,000.01, including tax and shipping pushing a subtotal over the line.
- **Offline network:** full suite with the network guard; plus a test that `--mode offline` never imports the xAI SDK.
- Write `docs/verification/robustness-<YYYY-MM-DD>.md` with what ran, results, and known limitations.

## Acceptance criteria

- [ ] All campaigns pass or each failure has a ticket and a documented limitation.
- [ ] Payment-uniqueness invariant holds across every campaign.
- [ ] Results document committed.
