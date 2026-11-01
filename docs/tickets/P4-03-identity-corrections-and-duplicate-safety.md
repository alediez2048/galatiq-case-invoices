# P4-03 — Identity corrections and duplicate safety

Phase: 4 · Status: todo · Depends on: P4-02, P2-10 · Requirements: P05, P13

## Context

Identity corrections must check both old and new identities for prior payment, so changing an extracted vendor or invoice number cannot evade duplicate protection ([system design — persistence](../systemsdesign.md#persistence-and-transaction-boundaries)).

## Scope

- When a correction changes vendor key or invoice-number key:
  - If **either** the old or the new identity has a payment → `already_paid` / `revision_after_payment`; no new version.
  - If the new identity already exists with other versions → apply P2-10 revision rules against that identity (`duplicate` or `version_conflict`).
  - Otherwise move the invoice to the new identity in one transaction and record both identities in the audit event.
- The P0-04 uniqueness constraint on payments stays the final guard.

## Acceptance criteria

- [ ] Pay INV-1001; process a variant where the number appears only on an unrecognized line (`Our ref INV-1001`), so it is extracted as missing; correcting it to `INV-1001` citing that line → blocked as already paid.
- [ ] Correcting a vendor so the identity collides with an unpaid existing invoice → `version_conflict`.
- [ ] Concurrent identity corrections on two records toward the same identity: at most one succeeds (thread test).
