# P6-04 — Submission documentation and business-impact narrative

Phase: 6 · Status: todo · Depends on: P6-01, P6-03 · Requirements: A10

## Context

Completion requires documenting architecture, setup, assumptions, limitations, and example results in the public fork, and preserving the original assignment README ([requirements — completion](../requirements.md#evaluation-and-completion)). The evaluation includes **Presentation**: translating technical decisions into business impact. Scenario figures ($2M/year, 30% error rate, five-day delay) are inputs, not measured outcomes or promised savings.

## Scope

- README: add a solution section that links into `docs/` while keeping the assignment text intact (see decision below).
- Content:
  - What it does in one paragraph, plus a screenshot.
  - Quick start: prerequisites (Python 3.12, Node version), install from locks, seed, run CLI on 1001, start API + UI, run tests, run live smoke test.
  - Architecture summary with the diagram from the system design.
  - Results table for all 20 supplied files (from P2-11 and the live verification record).
  - How each evaluation criterion is addressed, linking evidence (tests, verification records, demo).
  - Business impact: which pain points each design choice targets (error rate → deterministic checks and evidence; delay → auto-pay for clean invoices ≤ USD 10,000; email-chain approvals → human approval queue), with any time/cost estimates clearly labeled illustrative and their assumptions visible.
  - Assumptions and limitations (simulated payment, no PO/vendor master, no OCR, USD-only settlement, local single operator, offline/LLM interpretation).
- `docs/development.md` finalized; all design docs' status lines updated from "planned" to what was actually built.

## Decision needed

**Where solution docs live relative to the assignment text.** Recommendation: a short "Solution" section at the top of `README.md` (overview, quick start, links) followed by the untouched assignment text under an "Original assignment" heading. Alternative: keep `README.md` unchanged and put everything in `docs/SOLUTION.md`, at the cost of graders landing on the assignment instead of the solution.

## Acceptance criteria

- [ ] A reader following only the README can install, seed, and run the CLI and UI on a clean machine.
- [ ] Original assignment text is present and unaltered (diff check against commit `3452e95`).
- [ ] Every claim in the README links to a test, verification record, or demo step.
- [ ] No promised savings; illustrative numbers are labeled with their assumptions.
