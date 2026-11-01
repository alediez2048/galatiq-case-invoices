# P5-06 — Empty workspace, overview, and invoice list

Phase: 5 · Status: todo · Depends on: P5-03, P5-05 · Requirements: P07

## Context

[Mockup screens 1 and 4](../mockup.md#screen-1--first-visit--empty-workspace): empty workspace with the hero copy, a restrained green wave mesh, and "Upload invoice" / "Try a sample"; overview with metric cards, mock-paid totals by currency, recent invoices, and "View all invoices".

## Scope

- Empty state: "From invoice to decision. Every check visible."; wave mesh only here (decorative, `aria-hidden`, disabled under reduced motion); "No invoices processed yet."
- "Try a sample" opens a selection panel (from `GET /api/samples`); choosing a sample goes to the add-invoice flow (P5-07), never straight to processing.
- Setup readiness notice appears only when actionable (inventory missing, live credentials missing while live selected).
- Overview: cards for unique invoices, mock paid, needs review, rejected, plus awaiting approval and failed cards when non-zero (never hidden to keep four cards). "Mock paid: USD …" per currency with "No real funds transferred."
- Invoices list: columns invoice, vendor, total (right-aligned, explicit currency, tabular figures), outcome, open; filters by outcome and mode; search; "No invoices match these filters." with Clear filters; "Loading invoice history…" without fabricated rows.
- Narrow widths: summary cards instead of the wide table (P5-10 checks).

## Acceptance criteria

- [ ] With the 1001/1004/1002/1014 data from P5-03, the overview matches mockup screen 4 values.
- [ ] Failed count appears as soon as a failed invoice exists.
- [ ] All values come from the API; no hard-coded illustrative data remains.
