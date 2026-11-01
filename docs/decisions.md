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

## Round 3 — Plan review (2026-11-01)

After an independent review of the 62 implementation tickets, the user approved:

1. **Model disagreement waits for a human.** When the deterministic checks find no blocker but the model's final recommendation is reject or review, the invoice enters `awaiting_human_approval` with a `model_disagreement` finding, reusing the approve/decline actions. It is not rejected outright; a human cannot override a real blocker this way.
2. **Scope cut line.** The tickets index marks a core set that ships regardless and a deferred set (identity corrections, review CLI, accessibility audits, fuzzing, audit export, thread-concurrency tests) that ships only if time remains.
3. **Provider adapter stays on the official `xai_sdk`**; the reasoning interface still allows a second adapter later.
4. **Native execution for Phase 0**: the session implements the plan tasks directly with one fresh end-of-phase review.

Design corrections adopted without needing a user decision: run status and invoice status are separate enums; findings have a `review` severity distinct from `blocker`; duplicate detection ignores failed runs and linked retry/mode-switch runs and always records a run; the policy gate accepts a version-bound human review as input; the per-invoice model budget counts top-level steps, not tool turns.

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
