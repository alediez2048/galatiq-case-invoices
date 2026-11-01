# P5-08 — Invoice detail and outcome states

Phase: 5 · Status: todo · Depends on: P5-03, P5-05 · Requirements: P07, P08

## Context

[Mockup screens 5 and 6 and other essential states](../mockup.md#screen-5--invoice-detail-successful-outcome): header with outcome, total, due date, and mode; stage strip; source and decision panels; Decision / Checks / History tabs; line items with requested vs available; receipt; download. No private model reasoning or decorative "thinking" transcripts.

## Scope

- Header: invoice number · vendor, outcome badge, total with currency, due date, mode of the run; "Overdue" warning showing the evaluation date when applicable.
- Source panel: readable text/rows with evidence anchors highlighted on hover/focus from findings; PDF page preview when available with extracted text fallback and an explicit preview limitation.
- Decision tab: recommendation, critique summary, final policy result, mode, provider/model when live; offline marked "simulated".
- Checks tab: each check with observed vs expected and source reference; normalization events (raw → normalized, provenance).
- History tab: stage events, prior runs, versions, corrections, human reviews.
- Line items: requested, available, unit price, line total; "Exceeds stock by N" for shortfalls.
- Receipt block only when a payment exists: persisted reference, time, "No real funds transferred."
- Rejection view: primary blocking reason first; "Add corrected invoice" (opens P4-05 corrected-submission flow); no "Approve anyway".
- Other states with mockup copy: duplicate ("Already processed. No additional payment." with link to original), version conflict, revision after payment ("Earlier version already mock paid. Revised version blocked from additional payment." with prior receipt), unreadable/unsupported/OCR/oversized, missing fields, contradictory totals ("Stated total exceeds calculated total by USD 50.00."), provider unavailable, processing failure.
- Download result JSON from the persisted endpoint.

## Acceptance criteria

- [ ] Detail views verified for 1001 (paid), 1002 (rejected), 1013 (totals + stock), 1012 (normalization events), 1014 (EUR review), 1011 PDF (duplicate), 1004 revised after 1004 (revision after payment).
- [ ] Every state in the mockup's "Other essential states" table has a component test.
- [ ] No illustrative values remain in components.
