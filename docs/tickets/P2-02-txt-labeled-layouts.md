# P2-02 — TXT extraction: labeled layouts, label typos, email bodies

Phase: 2 · Status: todo · Depends on: P1-01 · Requirements: A01, A02, P04

## Context

P1-01 handles INV-1001's clean labels. The other labeled TXT fixtures vary:

- **1002**: misspelled labels: `INVOCE`, `Vndr:`, `Inv #:`, `Dt:`, `Due Dt:`, `Itms:`, `Amt:`, `Pymnt Terms:`. Item line `GadgetX  qty 20   @ $750 ea`. Only a total (`Amt`) is stated.
- **1003**: clean labels, `Due Date: yesterday`, a `Notes:` line with urgent wording.
- **1008**: an email: `From:/To:/Subject:` headers, indented `Vendor:/Invoice:/Date:/Due:` labels, bullet items `- SuperGizmo  x12  $400.00 each`, trailing signature that repeats the vendor name.

## Scope

- Label dictionary mapping canonical fields to known variants (`vendor` ← `Vendor`, `Vndr`, `FROM`; `invoice_number` ← `Invoice Number`, `Invoice`, `Inv #`, `INV NO`; `due_date` ← `Due Date`, `Due Dt`, `Due`; `total` ← `Total Amount`, `Total`, `Amt`, `TOTAL`, `Grand Total`; etc.). Each match that uses a non-canonical variant emits a `NormalizationEvent` with provenance `rule:label_alias`.
- Item-line patterns: `qty: N  unit price: $X`, `qty N @ $X ea`, `- NAME xN $X each`.
- Capture `Notes`/free text as evidence only. Urgent or payment-pressure wording emits `risk_signal_urgency` (info); it never changes business rules (see [constraints — security](../contraints.md#security-and-trust-boundaries)).
- Email headers are ignored for invoice fields; the `From:` address is not treated as vendor identity.
- Unmatched lines in the items block become extraction issues.

## Out of scope

Table layouts (P2-03). Date parsing and relative dates (P2-09). Item aliases (P2-08).

## Acceptance criteria

- [ ] 1002 extracts vendor `Gadgets Co.`, invoice `1002`, GadgetX ×20 @ 750, total 15,000.00, with label-alias events for each misspelled label.
- [ ] 1003 extracts FakeItem ×100 @ 1,000.00, total 100,000.00, raw due date `yesterday`, and `risk_signal_urgency`.
- [ ] 1008 extracts vendor `NoProd Industries`, invoice `INV-1008`, SuperGizmo ×12 @ 400.00, MegaSprocket ×6 @ 850.00, total 9,900.00.
- [ ] Every value has line-number evidence.
