# P4-07 — Review workflow acceptance fixtures and tests

Phase: 4 · Status: done · Depends on: P4-01 – P4-06 · Requirements: P10, P13, P14

## Context

[Requirements — evaluation and completion](../requirements.md#evaluation-and-completion) require added fixtures: valid USD 10,000.00 and 10,000.01, an evidence-backed extraction mistake, an actual source-document error, a correction after approval, repeated/stale approval requests, and a live-provider failure. The supplied high-value invoices all have blockers, so they cannot show the eligible approval path.

## Scope

Fixtures in `tests/fixtures/review/` (threshold fixtures reused from P3-06):

| Fixture | Scenario | Expected |
| --- | --- | --- |
| `valid_10000_00.json` | Boundary, auto path | `paid_mock`, no human action |
| `valid_10000_01.json` | Boundary, human path | `awaiting_human_approval` → approve → `paid_mock` |
| `extraction_mistake.txt` | Ambiguous OCR the parser cannot resolve; source supports one value | `needs_review` → correction → revalidated outcome |
| `source_error.json` | Stated total wrong in the document itself | `rejected`; correction refused (`correction_not_in_source`) |
| `correction_after_recommendation.txt` | Agent recommended approve on v1; reviewer corrects to v2 | v1 decisions invalidated; v2 re-recommended and critiqued |
| (sequence) | Approve with stale version after correction | `stale_version`, no payment |
| (sequence) | Repeated approve | Same receipt, one payment |
| (sequence) | Process restart between waiting and approval | Approval still works; one payment |
| (sequence) | Live-provider failure during re-review after correction | `failed` recoverable, unpaid; retry succeeds (scripted fake) |

- Every test asserts the payment-count invariant: one payment per business identity at most.
- Update the PRD Phase 4 exit-criteria checkboxes with links to passing tests.

## Acceptance criteria

- [x] All scenarios pass offline with the network guard, plus the live-failure scenario with the scripted fake. (`tests/test_review_acceptance.py`)
- [x] No blocker or review finding can be cleared by approve/decline (property-style test over all such codes); a correction may change only extracted values that the source supports, and the corrected version is re-validated from scratch rather than having findings removed. (`tests/test_review_acceptance.py::test_matching_approval_never_clears_a_gating_finding`, `::test_approve_refused_for_every_recorded_gating_code`; `tests/test_corrections.py`)

## As built (2026-11-02)

- `tests/test_review_acceptance.py` runs every row of the table above through the public calls, each ending with at most one payment for its invoice. The restart row runs `main.py` in a subprocess and approves from the test process. Fixtures live in `tests/fixtures/review/` and `tests/fixtures/threshold/`.
- **Thread tests deferred** (cut line): no test runs two review actions on separate threads.
