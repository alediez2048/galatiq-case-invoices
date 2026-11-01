# P1-01 — Source intake and clean TXT extraction

Phase: 1 · Status: todo · Depends on: P0-03 · Requirements: A01 (TXT only), A02, P04 (minimal)

## Context

Phase 1 only needs INV-1001 end to end. Its layout is labeled lines (`Vendor:`, `Invoice Number:`, `Date:`, `Due Date:`), an `Items:` block with `qty:` / `unit price:` columns, then `Subtotal`, `Tax (0%)`, `Total Amount`. It states no currency; amounts carry `$` only. Messy TXT variants, other formats, and input limits are Phase 2.

## Scope

- `src/invoice_processing/intake.py`: validate the path exists, is a regular file, and has a supported extension; read bytes; compute SHA-256; build a `SourceDocument` with parser version.
- `src/invoice_processing/parsers/txt.py`: decode as UTF-8 with explicit errors (no silent replacement); extract labeled fields and item lines into an `InvoiceDraft` with line-number evidence for every value. Unparseable lines become extraction issues, not dropped silently.
- `src/invoice_processing/normalize.py` (minimal): build a `NormalizedInvoice` from the draft. Parse ISO dates and `$1,234.56` amounts. Canonical vendor key = case/whitespace-normalized vendor name.
- **USD assumption (pulled forward from Phase 2):** when no currency is stated, set `USD` and emit a `currency_assumed_usd` info finding plus a `NormalizationEvent` with provenance `rule:dataset_usd_assumption`, citing the `$` evidence. Required for INV-1001 to pass the P0-06 currency check.

## Out of scope

JSON/CSV/XML/PDF parsers, label typos, aliases, OCR artifacts, relative dates, size/page limits (all Phase 2).

## Acceptance criteria

- [ ] INV-1001 yields vendor `Widgets Inc.`, invoice `INV-1001`, due date `2026-02-01`, WidgetA ×10 @ 250.00, WidgetB ×5 @ 500.00, total 5,000.00, currency USD with a recorded assumption.
- [ ] Every extracted value has a line-number evidence reference.
- [ ] A nonexistent path, a directory, and an unsupported extension each fail with a specific error, before any processing record is created.
- [ ] The same bytes always produce the same content hash.
