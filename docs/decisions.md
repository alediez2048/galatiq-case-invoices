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

## Round 4 — Open-question resolution (2026-11-01, user session)

Source for every item below: user, 2026-11-01 session. Tracked by [P6-05](tickets/P6-05-open-question-resolution.md).

<a id="d-cli-mode"></a>
1. **Default CLI mode is `offline`** (P6-05 row 7). When `--mode` is omitted the CLI runs offline and labels it. Recorded in the tickets index (P1-09).
<a id="d-inv1012"></a>
2. **INV-1012 auto-pays as `paid_mock`** (row 8). All corrections are rule-backed and the total is USD 9,975.00, below the 10,000 threshold. Asserted in `tests/test_acceptance.py` for both `invoice_1012.txt` and `invoice_1012.pdf`.
<a id="d-pdf"></a>
3. **PDF extraction matches the generator source** (row 5, resolved by P2-07). `pdfplumber` output for the three committed PDFs (1011, 1012, 1013) matches the generator content. Extracted text is committed as snapshots in `tests/fixtures/pdf_text/` and asserted in `tests/test_parser_pdf.py`, so a dependency change that alters extraction is caught. Caveat: 1011 PDF carries only a total (no subtotal or tax), unlike 1011 TXT; this is handled as absent, not zero.
<a id="d-process"></a>
4. **Process: subagent-driven execution per phase; merge straight to main, no pull requests.** This is a working-method choice, not a product decision.
<a id="d-speedups"></a>
5. **Scope speed-ups for Phases 3–6.** Apply the cut line; lighter review for mechanical work; bundle tickets; run phases back to back. The user will supply the xAI key later, so only the live smoke test P3-10 waits on it. This partly addresses row 2 (credentials will exist); the model choice and the live-testing budget are still to be confirmed at that point (see [limitations](limitations.md#l-live-credentials)).
<a id="d-inv1007"></a>
6. **Data finding: INV-1007's stated total is 110.00 short.** Stated total 15,525.00 versus subtotal 14,750.00 plus 6% tax = 15,635.00. It is rejected for `quantity_exceeds_stock` and `total_mismatch` (see the correction note in [requirements](requirements.md) and `test_invoice_1007` in `tests/test_acceptance.py`). The earlier wording that its arithmetic passes was wrong; the outcome (rejected) is unchanged.

Decisions from earlier rounds that close ticket rows: model disagreement waits for a human (round 3, item 1; row 11), scope cut line (round 3, item 2; row 12), provider adapter stays on `xai_sdk` (round 3, item 3; row 13).

## Round 5 — Answers to the P6-05 questions (2026-11-01, user session)

The user answered: "best practice" for Q1, Q2, Q4, Q5 and Q7; Q6 confirmed as proposed. Q3 (deadline, evaluator machine) stays open.

<a id="d-dual-mode"></a>
1. **Offline and live modes (Q1).** Ship both, clearly labeled. `offline` stays the default: deterministic, no network, reproducible on any machine, with the reasoning step marked "simulated". `live` (explicit `--mode live` plus an xAI key) is the primary agent demo on real Grok. Both share the same parsers, validation, gate and payment service, so a mode never changes business rules. The README states this interpretation up front.
<a id="d-live-model-budget"></a>
2. **Model and live-testing budget (Q2).** The model is never hard-coded: `XAI_MODEL` names it, and the live smoke test (P3-10) records the exact model id, SDK version, calls and token usage in `docs/verification/`. Use the current Grok 4 flagship available to the key at that time. Spend is bounded three ways: ≤ 6 top-level model steps per invoice (enforced in code), one smoke run of about 11 invoices per verification, and a spending limit set in the xAI console before the first live run (recommended USD 10 for P3-10 plus demo rehearsals). The verification record estimates the cost of each run.
<a id="d-eur"></a>
3. **EUR and other non-USD currencies (Q4).** Review-only. The amount and currency are preserved, never converted, and the invoice ends `needs_review` (`unsupported_currency`, `non_usd_currency`). Rationale: no trusted exchange-rate source and no non-USD settlement path exist, and silently converting money is the riskier error. A human cannot pay it in this prototype.
<a id="d-revisions-inventory"></a>
4. **Revisions and inventory (Q5).** A changed version of an already-paid identity is held for review (`revision_after_payment`) and never paid again; a changed version of an unpaid identity is a `version_conflict` until the corrected-submission flow (P4-05) supersedes it. Inventory is checked per item against current stock, with repeated lines aggregated; there is no reservation and paying does not decrement stock. This is a documented prototype simplification: a production system would reserve stock on approval and decrement it on payment inside the same transaction.
<a id="d-supersede"></a>
5. **Corrected submissions (Q6, confirmed as proposed).** A corrected invoice supersedes earlier versions only when none of them is paid, approved or awaiting human approval, and only through an explicit "Add corrected invoice" action with a required reason. A plain upload under the same identity stays a `version_conflict`. P4-05 implements this.
<a id="d-readme"></a>
6. **README layout (Q7).** Solution first, assignment preserved: a short summary, quickstart (install, seed, run one invoice, run all samples), the offline/live modes, architecture overview, results table, decisions and limitations links, then the original assignment text unchanged under an "Original assignment" heading at the end. P6-04 implements this.

## Consequences and verification

- Add a persisted human-approval waiting state and version-bound correction/approval operations.
- Reject stale approvals; repeated actions and cross-mode runs cannot create duplicate payments.
- Add valid threshold-boundary fixtures: supplied high-value examples also fail other checks.
- Verify source errors cannot be disguised as extraction corrections.
- Verify real provider execution separately from controlled offline tests.
- Preserve the original assignment README. The offline/API conflict remains an evaluator interpretation risk despite the approved project approach.
- Current HTML is a visual prototype of the earlier flow. React, FastAPI, live Grok, and actionable review are planned implementation work; documentation updates do not implement them.

## Remaining open details

Still open and disclosed in [limitations](limitations.md), with drafted questions in [P6-05](tickets/P6-05-open-question-resolution.md#questions-to-send-needs-user-approval): offline-versus-LLM interpretation, Grok model and live-testing budget, deadline and target machine, EUR settlement, evaluator view on revisions and inventory semantics, the corrected-submission supersede rule, and README layout. Exact dependency versions and detailed API contracts are settled in the tickets as they are built, not here.

## Documents updated

- [Requirements](requirements.md): acceptance criteria and approval policy.
- [Constraints](contraints.md): live/offline interpretation and expanded scope.
- [System design](systemsdesign.md): API boundary, review state, versioned corrections, and payment gates.
- [Technology stack](techstack.md): React/TypeScript, FastAPI, and verification plan.
- [Style guide](styleguide.md): frontend direction.
- [Experience mockup](mockup.md): correction and approval interactions and updated demo sequence.
