# P2-11 — Fixture acceptance suite

Phase: 2 · Status: done · Depends on: P2-01 – P2-10 · Requirements: P10, A01–A03

## Context

Phase 2 exits when all 20 supplied files have asserted outcomes. Each unique invoice is evaluated against a fresh seed snapshot; duplicate behavior is tested separately in a persistent ledger (P2-10) ([requirements — sample acceptance matrix](../requirements.md#sample-acceptance-matrix)). Tests assert statuses and finding codes, not prose.

## Scope

- Table-driven test, one case per file, each on a fresh temporary seeded database, offline mode, fixed evaluation date `2026-01-31`.
- A coverage test that fails if any file in `data/invoices/` has no case.
- Expected outcomes:

| File | Status | Key findings |
| --- | --- | --- |
| 1001.txt | `paid_mock` 5,000.00 | `currency_assumed_usd` |
| 1002.txt | `rejected` | `quantity_exceeds_stock` (GadgetX 20 > 5), `terms_inconsistent`, label-alias events |
| 1003.txt | `rejected` | `zero_stock` (FakeItem), `due_date_unresolved`, `risk_signal_urgency` |
| 1004.json | `paid_mock` 1,890.00 | — |
| 1004_revised.json | `paid_mock` 5,940.00 (alone) | — |
| 1005.json | `rejected` | `quantity_exceeds_stock` (GadgetX 8 > 5) |
| 1006.csv | `paid_mock` 2,750.00 | `currency_assumed_usd` |
| 1007.csv | `rejected` | `quantity_exceeds_stock` (WidgetA 20 > 15, WidgetB 15 > 10), `total_mismatch` (expected 15,635.00, observed 15,525.00) |

_Correction 2026-11-01: the table first listed only the stock findings. The file's stated total (15,525.00) is 110.00 below subtotal 14,750.00 + 6% tax 885.00 = 15,635.00, so `total_mismatch` also fires. The outcome is still `rejected`._

| 1008.txt | `rejected` | `unknown_item` ×2 |
| 1009.json | `rejected` | `missing_vendor`, `missing_due_date`, `non_positive_quantity`, `non_positive_total`, `subtotal_mismatch` |
| 1010.txt | `paid_mock` 7,185.00 | `rule:item_qualifier` event; WidgetA aggregated 12 |
| 1011.txt / .pdf | `paid_mock` 3,000.00 | — |
| 1012.txt / .pdf | `paid_mock` 9,975.00 | `rule:item_spacing`, `rule:ocr_digit`, `rule:invoice_number_format` events |
| 1013.json / .pdf | `rejected` | `quantity_exceeds_stock` ×3 (22/18/9), `total_mismatch` 50.00 |
| 1014.xml | `needs_review` | `unsupported_currency` |
| 1015.csv | `paid_mock` 6,500.00 | `currency_assumed_usd` |
| 1016.json | `rejected` | `unknown_item` (WidgetC) |

- Run every case with the network guard active; assert `mock_payment` is never called for non-`paid_mock` cases.
- Update the PRD Phase 2 checkboxes with links to the passing tests.

## Decision needed

**1012 expected outcome.** The table assumes `paid_mock` because every correction is rule-backed and stock, arithmetic, and total (9,975.00 ≤ 10,000) pass. The requirements also say "unresolvable ambiguity goes to review." Confirm `paid_mock` is the intended demo outcome, or whether OCR-corrected invoices should always stop at `needs_review`.

**Resolved 2026-11-01:** the user confirmed INV-1012 -> `paid_mock`.

## Acceptance criteria

- [x] All 20 cases pass from a clean clone.
- [x] The coverage test fails when a new file is added to `data/invoices/` without a case.
- [x] Suite runs in under 60 seconds.
