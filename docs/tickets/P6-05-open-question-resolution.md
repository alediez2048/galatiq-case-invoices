# P6-05 — Resolve or disclose open questions

Phase: 6 · Status: todo · Depends on: — (can start any time) · Requirements: A08, completion item 7

## Context

[Constraints — decisions to revisit](../contraints.md#decisions-to-revisit-before-implementation-or-submission) and [decisions — remaining open details](../decisions.md#remaining-open-details) list items that must be resolved or disclosed before submission. Ticket-level decisions raised during planning are also collected here.

## Scope

Track each item to a recorded resolution in `docs/decisions.md`, or a disclosure in the README limitations:

| # | Question | Source |
| --- | --- | --- |
| 1 | Does an offline simulator plus tested live integration satisfy the brief? | constraints |
| 2 | Grok credentials, model, and live-testing budget | constraints |
| 3 | Deadline and target evaluator machine | constraints |
| 4 | EUR settlement vs review-only | constraints |
| 5 | Actual PDF extraction vs generator source | constraints (resolved by P2-07 if no divergence) |
| 6 | Evaluator view on revision handling and inventory semantics | constraints |
| 7 | Default CLI mode when `--mode` is omitted | P1-09 |
| 8 | INV-1012 auto-pay vs always review | P2-11 |
| 9 | How corrected submissions supersede unpaid versions | P4-05 |
| 10 | README layout for solution vs assignment | P6-04 |

- Where the evaluator can be asked, draft the question; send only with the user's approval.
- Items decided earlier are marked resolved with a link to the decision.

## Acceptance criteria

- [ ] Every row has a resolution or a published disclosure.
- [ ] `docs/decisions.md` updated with any new decisions and their dates.
