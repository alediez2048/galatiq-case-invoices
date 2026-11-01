# P2-07 — PDF text extraction

Phase: 2 · Status: todo · Depends on: P2-01, P2-03 · Requirements: A01, A02

## Context

Three committed PDFs (1011, 1012, 1013) are single-page, unencrypted, text-based. `pdftotext -layout` output (checked 2026-11-01) matches the generator source:

- **1011 PDF**: labeled header, `Item Qty Unit Price Amount` table, **only a `Total:` line**: no subtotal or tax, unlike 1011 TXT.
- **1012 PDF**: identical text to 1012 TXT, including OCR-like artifacts.
- **1013 PDF**: header lines carry two fields each (`Invoice: INV-1013 … Date: 2026-01-24`, `Vendor: … Due: 2026-03-24`); a `Notes` column; footer `Subtotal 21,040.00`, `Tax (7%) 1,472.80`, `Grand Total 22,562.80`. No currency stated.

The fixture expectations come from generator source; [requirements](../requirements.md#sample-acceptance-matrix) requires verifying actual extraction from the committed bytes.

## Scope

- `parsers/pdf.py`: extract text per page with `pdfplumber`, preserving layout well enough for the P2-03 table extractor; evidence references are page + line.
- Split header lines containing two `Label: value` pairs.
- Treat a trailing free-text cell (1013 `Notes`) as a line note, not part of the amount.
- Record extractor name and version on the `SourceDocument`.
- Snapshot test: commit the extracted text of each PDF under `tests/fixtures/pdf_text/` and assert extraction matches it, so a dependency upgrade that changes output is caught.

## Acceptance criteria

- [ ] 1011 PDF yields WidgetA ×6, WidgetB ×3, total 3,000.00, no stated subtotal/tax (absent, not zero).
- [ ] 1012 PDF yields the same raw values as 1012 TXT.
- [ ] 1013 PDF yields eight lines with notes, invoice `INV-1013`, both dates, subtotal 21,040.00, tax 1,472.80, total 22,562.80, currency absent.
- [ ] Any difference between pdfplumber output and the `pdftotext` reading above is documented in the ticket before closing.
