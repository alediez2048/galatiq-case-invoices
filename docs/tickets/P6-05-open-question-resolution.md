# P6-05 — Resolve or disclose open questions

Phase: 6 · Status: in progress · Depends on: — (can start any time) · Requirements: A08, completion item 7

## Context

[Constraints — decisions to revisit](../contraints.md#decisions-to-revisit-before-implementation-or-submission) and [decisions — remaining open details](../decisions.md#remaining-open-details) list items that must be resolved or disclosed before submission. Ticket-level decisions raised during planning are also collected here.

## Scope

Track each item to a recorded resolution in `docs/decisions.md`, or a disclosure in [limitations](../limitations.md) (P6-04 links it from the README):

| # | Question | Source | Resolution |
| --- | --- | --- | --- |
| 1 | Does an offline simulator plus tested live integration satisfy the brief? | constraints | Disclosed: [limitations 1](../limitations.md#l-offline-vs-llm). Question Q1. |
| 2 | Grok credentials, model, and live-testing budget | constraints | Partly resolved (key supplied later, only P3-10 waits; [decision 5](../decisions.md#d-speedups)). Model and budget disclosed: [limitations 2](../limitations.md#l-live-credentials). Question Q2. |
| 3 | Deadline and target evaluator machine | constraints | Disclosed: [limitations 3](../limitations.md#l-deadline). Question Q3. |
| 4 | EUR settlement vs review-only | constraints | Disclosed (review-only assumed): [limitations 4](../limitations.md#l-eur). Question Q4. |
| 5 | Actual PDF extraction vs generator source | constraints (resolved by P2-07 if no divergence) | Resolved: [decision 3](../decisions.md#d-pdf); [limitations 5](../limitations.md#l-pdf). |
| 6 | Evaluator view on revision handling and inventory semantics | constraints | Disclosed: [limitations 6](../limitations.md#l-revisions). Question Q5. |
| 7 | Default CLI mode when `--mode` is omitted | P1-09 | Resolved `offline`, user 2026-11-01: [decision 1](../decisions.md#d-cli-mode). |
| 8 | INV-1012 auto-pay vs always review | P2-11 | Resolved auto-pay `paid_mock`, user 2026-11-01: [decision 2](../decisions.md#d-inv1012). |
| 9 | How corrected submissions supersede unpaid versions | P4-05 | Disclosed (recommendation as working assumption): [limitations 9](../limitations.md#l-supersede). Question Q6. |
| 10 | README layout for solution vs assignment | P6-04 | Disclosed: [limitations 10](../limitations.md#l-readme). Question Q7. |
| 11 | Model disagrees with a clean invoice → `awaiting_human_approval` | **Resolved 2026-11-01** (decisions.md round 3) | Resolved: [round 3, item 1](../decisions.md#round-3--plan-review-2026-11-01). |
| 12 | Scope cut line (core vs deferred) | **Resolved 2026-11-01** (tickets index) | Resolved: [round 3, item 2](../decisions.md#round-3--plan-review-2026-11-01); tickets index. |
| 13 | Provider adapter: official `xai_sdk` vs OpenAI-compatible client | **Resolved 2026-11-01**: keep `xai_sdk` | Resolved: [round 3, item 3](../decisions.md#round-3--plan-review-2026-11-01). |

- Where the evaluator can be asked, draft the question; send only with the user's approval.
- Items decided earlier are marked resolved with a link to the decision.

## Acceptance criteria

- [x] Every row has a resolution or a published disclosure (Resolution column).
- [ ] Drafted questions answered by the user; answers recorded in `docs/decisions.md` and the matching limitation updated or removed. The ticket closes then.
- [ ] `docs/decisions.md` updated with any new decisions and their dates.

Also recorded 2026-11-01 (user): process choices (subagent-driven, merge to main without PRs) and the Phase 3–6 speed-ups, in [decisions round 4](../decisions.md#round-4--open-question-resolution-2026-11-01-user-session); INV-1007's 110.00 total discrepancy, [decision 6](../decisions.md#d-inv1007).

## Questions to send (needs user approval)

Nothing below has been sent. Each can go to the evaluator or case contact once the user approves the wording; Q2 and Q3 are for the user.

- **Q1 (row 1, evaluator):** "The brief asks for LLM-based reasoning and also says the prototype must not depend on external APIs at runtime. We provide an `offline` mode (deterministic rules plus a clearly labeled simulated reasoning step, no network) and a separate `live` mode that calls Grok when an xAI key is supplied. Is that an acceptable reading, or do you expect real model inference with no network (e.g. a local model)?"
- **Q2 (row 2, user):** "Which Grok model should the live mode use, and what is the maximum spend you allow for live testing (P3-10 and the live demo)? Current plan: you supply the xAI key later and only the smoke test waits on it."
- **Q3 (row 3, user/evaluator):** "What is the submission deadline, and what machine will the evaluator run this on (OS, Python version, whether internet is available for `pip install` and for live mode)? Current assumption: a recent Python with internet during install, no hard deadline, cut line applied."
- **Q4 (row 4, evaluator):** "INV-1014 is invoiced in EUR 4,125. We treat non-USD as review-only: it is never converted or paid and ends `needs_review`. Is that the expected handling, or should EUR be paid (and at what exchange rate)?"
- **Q5 (row 6, evaluator):** "For a revised invoice after the original was paid (INV-1004 revised), we hold it for review rather than paying again. For inventory we check each line's quantity against current stock, aggregating repeated items, with no reservation, and paying does not decrement stock. Does this match your intent?"
- **Q6 (row 9, user):** "When a vendor sends a corrected invoice for an unpaid, rejected or needs-review invoice, we propose that it supersedes the earlier versions only if none is paid, approved or awaiting human approval, and only through an explicit 'Add corrected invoice' action with a reason; a plain upload of the same identity stays a `version_conflict`. Confirm or change?"
- **Q7 (row 10, user):** "README layout: put our solution section (setup, run, limitations, business impact) at the top and preserve the original assignment text below it. Confirm?"
