# P4-05 — Review queue and corrected-invoice submissions

Phase: 4 · Status: todo · Depends on: P4-02, P4-04 · Requirements: P07 (data), P13

## Context

The review queue separates extraction corrections, eligible high-value approvals, and unresolved blockers ([mockup — screen 7](../mockup.md#screen-7--needs-review)). Rejected invoices offer "Add corrected invoice", which opens the normal submission flow, does not erase the previous result, and does not bypass revision checks ([mockup — screen 6](../mockup.md#screen-6--invoice-detail-rejection)).

## Scope

- `review.list_queue()` → waiting invoices grouped as `correctable_extraction`, `awaiting_human_approval`, `unresolved_blocker` (e.g. EUR, version conflict), each with reason codes, current version, and `AllowedActions`.
- `review.allowed_actions(invoice_id)` used by CLI/API so clients never infer permissions themselves.
- Corrected-invoice submission: a new source for an existing, **unpaid** identity whose prior versions are all `rejected`, `needs_review`, or `failed`:
  - Recorded as a new version with `origin = source`, linked to the prior version.
  - Goes through full processing.
  - Prior versions stay as history with `version_status = superseded` (the one mutable column on `invoice_versions`, P4-01); `invoices.status` becomes the new version's outcome.

## Decision needed

P2-10 sends any changed content under an existing identity to `version_conflict`, which would trap every corrected invoice. Recommendation: a new source **supersedes** prior versions only when none of them is paid, approved, or `awaiting_human_approval`, and the operator submits it through "Add corrected invoice" for that invoice (explicit link plus a reason). A plain upload with the same identity still hits `version_conflict`. Confirm before implementing.

## Acceptance criteria

- [ ] INV-1014 appears under `unresolved_blocker` with no approve action.
- [ ] `valid_10000_01` appears under `awaiting_human_approval` with approve/decline.
- [ ] A corrected INV-1013 (total 22,512.80, quantities within stock) submitted via the corrected-invoice path → original marked superseded, new version processed normally.
- [ ] The same corrected file uploaded without the link → `version_conflict`.
