# P2-10 — Duplicates, alternate formats, and revisions

Phase: 2 · Status: done · Depends on: P2-04, P2-07, P2-08, P2-09, P1-02 · Requirements: P05

## Context

P1-07 only detects byte-identical files. Phase 2 must also handle the same invoice in another format (1011, 1012, 1013) and a changed version under the same identity (1004 / 1004 revised). [System design — revision policy](../systemsdesign.md#persistence-and-transaction-boundaries): identical content returns the prior outcome; different content under the same identity goes to review before payment; a previously paid identity blocks all additional versions; never pick whichever file was processed last.

## Scope

- Business identity = vendor key + invoice-number identity key (P2-08).
- **Refine the P1-02 semantic hash** to cover payable content only: identity, currency, due date, and canonical lines (item, quantity, unit price) plus the final total. Exclude stated subtotal/tax lines, notes, terms text, filename, and layout, because 1011 PDF omits the subtotal and tax lines that 1011 TXT states.
- After normalization, before validation (same exemptions as P1-07: a prior `failed` run is not a duplicate; runs linked via `retry_of` / `mode_switch_of` skip this check; an explicitly requested offline run after a live `awaiting_human_approval` is therefore a separate labeled run that never inherits the live recommendation, per constraints):
  - Same identity + same semantic hash → run finishes `duplicate`, referencing the prior run, outcome, and receipt; `invoices.status` unchanged.
  - Same identity + different hash + prior version paid → `needs_review` with `revision_after_payment` (severity `review`). No payment; `invoices.current_version` stays on the paid version.
  - Same identity + different hash + prior version unpaid → `needs_review` with `version_conflict` (severity `review`); both versions stay unpaid.
- Record each new source and version even when blocked.
- At payment, the P0-04 uniqueness constraint remains the final guard.

## Out of scope

Choosing which version wins (needs a human; Phase 4 adds corrections, not version selection). Fuzzy vendor matching.

## Acceptance criteria (persistent ledger, in order)

- [ ] 1011 TXT → `paid_mock`; 1011 PDF → `duplicate`; one payment.
- [ ] 1012 TXT → `paid_mock`; 1012 PDF → `duplicate`; one payment.
- [ ] 1013 JSON → `rejected`; 1013 PDF → `duplicate` of that rejection.
- [ ] 1004 → `paid_mock`; 1004 revised → `needs_review` / `revision_after_payment`; one payment of 1,890.00.
- [ ] Reverse order: 1004 revised → `paid_mock` (5,940.00); 1004 → `needs_review` / `revision_after_payment`.
- [ ] Changing a filename or reformatting whitespace does not change the semantic hash.

## Behaviour (implemented)

- `ledger.check_identity` runs in the ingestion node after the version is recorded and the run
  is attached. In order: a payment for the identity on this version → `duplicate` of the paying
  run (or `new` when that run was interrupted, see below); a payment on another version →
  `revision_after_payment`. A payment always decides: run history is consulted only when the
  identity has no payment. Then the latest non-retry business outcome on this
  version → `duplicate`; one on another version → `version_conflict`; otherwise `new`. Failed
  and duplicate runs never count; provisional `pending:` identities and runs with `retry_of`
  are always `new`.
- A semantic `duplicate` run goes `extracted → duplicate`, ends the graph, references the prior
  run (`runs.prior_run_id`, result `prior_run_id`) and returns the prior receipt or `None`. Audit
  event `ingestion/duplicate` carries `prior_run_id`, `prior_status`, `match="semantic"`.
  `invoices.status` and `invoices.current_version` are unchanged.
- `revision_after_payment` / `version_conflict` are `review` findings (`observed` = prior run id)
  that continue through validation and the gate, so `R2_review` gives `needs_review` unless a
  blocker rejects first. The new source and version are always recorded.
- `payments.pay()` refuses with `PaymentNotAuthorized("revision_after_payment")` when the
  identity was already paid on another version; a replay of the paid version still returns the
  existing receipt (`created=False`).
- A run that paid and was then interrupted is marked `failed`, so a replay of the same version
  is `new` even when other runs of the identity have outcomes: it goes back through `pay()`,
  gets the existing receipt and finishes `paid_mock`, repairing `invoices.status`.
- A prior outcome carries a receipt only when that run itself paid; another run's payment is
  never reported as its receipt.
- `ledger.record_version` reuses the first source's payload when the semantic hash matches, so
  non-hashed fields (vendor display name, tax, shipping) come from the first file.
