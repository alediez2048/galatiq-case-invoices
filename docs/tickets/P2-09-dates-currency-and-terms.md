# P2-09 — Dates, currency, and payment terms

Phase: 2 · Status: todo · Depends on: P2-08 · Requirements: A02, P01, P04

## Context

Dates arrive as `2026-01-15`, `Jan 30 2026`, `January 27, 2026`, `26-Jan-2O26`, `01/28/2026`, and `yesterday`. Relative dates stay unresolved without a trustworthy reference date; past absolute due dates warn. Currency may be explicit (`USD`, `EUR`), implied by `$`, or absent. EUR is preserved and routed to review, never converted ([requirements — business policy](../requirements.md#business-policy)).

## Scope

- Date parser accepting ISO, `Mon D YYYY`, `Month D, YYYY`, `D-Mon-YYYY`, and slash dates. For `NN/NN/YYYY`, accept `MM/DD` only when unambiguous (one component > 12); otherwise `ambiguous_date` → `needs_review`. Apply after P2-08's `rule:ocr_digit`.
- Relative words (`yesterday`, `today`, `ASAP`, `immediately`) → `due_date_unresolved` (blocker for payment; not converted using the system clock).
- Due date earlier than invoice date → `due_before_invoice_date` (warning).
- Terms check: when `Net N` is stated and both dates parse, compare due date with invoice date + N days; mismatch → `terms_inconsistent` (warning).
- Currency: explicit code wins; `$` with no code → USD with `currency_assumed_usd` (generalizes the minimal P1-01 rule to every format); explicit `EUR` → `unsupported_currency` (review); conflicting signals (e.g. `€` with `USD`) → `currency_conflict` (review).

## Acceptance criteria

- [ ] 1002: invoice date 2026-01-30, due 2026-01-30, terms Net 30 → `terms_inconsistent`.
- [ ] 1003: `due_date_unresolved`; no date invented.
- [ ] 1007: `01/28/2026` → 2026-01-28. A constructed `02/03/2026` → `ambiguous_date`.
- [ ] 1012: `26-Jan-2O26` → 2026-01-26 with an OCR normalization event.
- [ ] 1014: currency EUR, `unsupported_currency`, final status `needs_review`.
- [ ] 1013 JSON (explicit USD) and 1013 PDF (assumed USD) normalize to the same currency, with the assumption recorded only for the PDF.
