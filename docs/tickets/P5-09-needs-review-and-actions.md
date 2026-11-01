# P5-09 — Needs-review queue, corrections, and approvals UI

Phase: 5 · Status: todo · Depends on: P5-04, P5-08 · Requirements: P13, P14

## Context

[Mockup screen 7](../mockup.md#screen-7--needs-review): queue separated into extraction corrections, eligible high-value approvals, and unresolved blockers. Correction form shows original source, extracted value, evidence, corrected value, required reason, "Save correction and revalidate", and "Saving invalidates prior approval." Approval panel shows the total, "All checks passed", recommendation + critique, required review reason, Decline / Approve mock payment, and "Payment waits for this action." These controls are additions not yet in the HTML mockup.

## Scope

- Queue view with three groups from `GET /api/review-queue`; actions rendered only from server-provided `AllowedActions`.
- Correction form: pick a finding/field, select evidence in the source panel (stores its location), enter corrected value and reason, reviewer name (remembered locally per browser as a convenience). Shows before/after; the submit copy reads "Save correction and revalidate. Saving invalidates prior approval; an eligible invoice up to USD 10,000 may auto-pay." On submit shows revalidation progress via the new run.
- Also surfaces the `model_disagreement` wait (clean invoice the model rejected) with the same approve/decline panel and the model's stated reasons.
- Approval panel for `awaiting_human_approval`: agent recommendation and critique, reason field, Decline and Approve mock payment, both bound to the displayed version.
- Unresolved blockers: explanation only (e.g. "EUR settlement remains blocked; human approval cannot override it.").
- On `409` stale responses: replace the panel with the current record and a "This invoice changed since you opened it" notice; nothing is resubmitted automatically.
- Version history visible: who changed what, when, why.

## Acceptance criteria

- [ ] Browser test: 10,000.01 fixture → approve → mock paid; approve again impossible in UI and refused by API.
- [ ] Browser test: correction on the extraction-mistake fixture → new version, revalidated, history shows old and new values.
- [ ] Browser test: two tabs; correct in one, approve in the other → stale notice, no payment.
- [ ] No approve control is ever rendered for `rejected` or `needs_review` invoices.
