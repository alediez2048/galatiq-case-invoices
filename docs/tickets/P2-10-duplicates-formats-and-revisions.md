# P2-10 — Duplicates, alternate formats, and revisions

Phase: 2 · Status: todo · Depends on: P2-04, P2-07, P2-08, P2-09, P1-02 · Requirements: P05

## Context

P1-07 only detects byte-identical files. Phase 2 must also handle the same invoice in another format (1011, 1012, 1013) and a changed version under the same identity (1004 / 1004 revised). [System design — revision policy](../systemsdesign.md#persistence-and-transaction-boundaries): identical content returns the prior outcome; different content under the same identity goes to review before payment; a previously paid identity blocks all additional versions; never pick whichever file was processed last.

## Scope

- Business identity = vendor key + invoice-number identity key (P2-08).
- **Refine the P1-02 semantic hash** to cover payable content only: identity, currency, due date, and canonical lines (item, quantity, unit price) plus the final total. Exclude stated subtotal/tax lines, notes, terms text, filename, and layout, because 1011 PDF omits the subtotal and tax lines that 1011 TXT states.
- After normalization, before validation:
  - Same identity + same semantic hash → `duplicate`, referencing the prior outcome and receipt.
  - Same identity + different hash + prior version paid → `needs_review` with blocker `revision_after_payment`. No payment.
  - Same identity + different hash + prior version unpaid → `needs_review` with `version_conflict`; both versions stay unpaid.
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
