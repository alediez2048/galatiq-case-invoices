# Agreed project decisions

Status: user-confirmed after two Matt Pocock grilling rounds. The user approved all recommendations and explicitly requested documentation updates. These are design decisions, not claims of implementation or evaluator approval.

## Round 1 — Product direction

1. **Real AI demonstration:** real Grok reasoning is the primary demo. Keep a separately selected and labeled offline simulator for reproducibility. Inventory and payments remain local/mock in both modes.
2. **Visual fidelity:** preserve the approved interactive mockup's layout and quality. Technology may change to meet that requirement.
3. **Controlled human review:** operators can resolve eligible extraction exceptions and resume processing. Hard payment blockers remain non-overridable.

## Round 2 — Implementation consequences

1. **React + TypeScript and FastAPI:** replace the Streamlit proposal. FastAPI and the CLI share Python processing logic, with LangGraph and SQLite retained.
2. **Evidence-backed corrections:** preserve the original document and prior extracted values. Require a correction reason, record the reviewer and version history, invalidate earlier approval, and rerun validation and agent review. Actual source-document errors require a corrected invoice.
3. **High-value approval:** otherwise-valid USD totals above 10,000 require explicit human approval after recommendation and critique. Eligible clean totals at or below 10,000 may auto-pay through the mock service. No human action can override hard blockers.
4. **Live failure behavior:** failed Grok reasoning leaves the invoice unpaid with an actionable error and explicit retry. Offline simulation requires a separate selection/run and never silently replaces live processing.

## Consequences and verification

- Add a persisted human-approval waiting state and version-bound correction/approval operations.
- Reject stale approvals; repeated actions and cross-mode runs cannot create duplicate payments.
- Add valid threshold-boundary fixtures: supplied high-value examples also fail other checks.
- Verify source errors cannot be disguised as extraction corrections.
- Verify real provider execution separately from controlled offline tests.
- Preserve the original assignment README. The offline/API conflict remains an evaluator interpretation risk despite the approved project approach.
- Current HTML is a visual prototype of the earlier flow. React, FastAPI, live Grok, and actionable review are planned implementation work; documentation updates do not implement them.

## Remaining open details

Deadline, credentials/model choice, live-testing budget, evaluator clarification, exact dependency versions, detailed API contracts, and target machine verification remain open. The decisions above settle the two requested rounds, not every implementation detail.

## Documents updated

- [Requirements](requirements.md): acceptance criteria and approval policy.
- [Constraints](contraints.md): live/offline interpretation and expanded scope.
- [System design](systemsdesign.md): API boundary, review state, versioned corrections, and payment gates.
- [Technology stack](techstack.md): React/TypeScript, FastAPI, and verification plan.
- [Style guide](styleguide.md): frontend direction.
- [Experience mockup](mockup.md): correction and approval interactions and updated demo sequence.
