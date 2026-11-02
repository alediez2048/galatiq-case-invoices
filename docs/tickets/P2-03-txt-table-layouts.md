# P2-03 — TXT extraction: column tables and footer totals

Phase: 2 · Status: done · Depends on: P2-02 · Requirements: A01, A02, P04

## Context

Three TXT fixtures use column tables with a header row and right-aligned footer totals:

- **1010**: `Description  Qty  Rate  Amount`; footer `Subtotal`, `Sales Tax`, `Shipping`, `TOTAL`; a line `WidgetA (rush order)  4  $300.00  $1,200.00`.
- **1011**: `Item  Qty  Unit Price  Amount` between dashed rules; footer `Subtotal`, `Tax (0%)`, `Total`.
- **1012**: letter-spaced title `I N V O I C E`, `FROM:` vendor with a `(formerly FastShip Ltd.)` continuation line, `ITEM QTY PRICE TOTAL`, item names with spaces (`Widget A`, `Gadget X`), OCR artifacts (`2O26`, `$3,500.O0`), and a multi-line `NOTES:` block.

The same extractor will be reused for PDF text (P2-07), whose `pdftotext -layout` output has the same shape.

## Scope

- Detect a header row by known column names (`Item`/`Description`/`ITEM`, `Qty`/`QTY`, `Unit Price`/`Rate`/`PRICE`, `Amount`/`TOTAL`) and parse following rows by whitespace-separated columns, tolerating dashed separator lines.
- Item names may contain spaces and parenthetical qualifiers; keep the raw name for P2-08 to canonicalize.
- Footer parsing for `Subtotal`, `Tax (N%)`/`Sales Tax`, `Shipping`, `Total`/`Grand Total`; record a stated tax rate when present.
- Vendor continuation lines (`(formerly …)`) are kept as evidence, not merged into the vendor name and not used for identity.
- Raw tokens are preserved exactly, including `2O26` and `3,500.O0`; correction happens in P2-08/P2-09 with provenance.

## Acceptance criteria

- [ ] 1010 extracts invoice number `INV-1010` (from the `INVOICE #INV-1010` title line), vendor `Consolidated Materials Group`, four lines including raw name `WidgetA (rush order)`, subtotal 6,700.00, tax 335.00, shipping 150.00, total 7,185.00.
- [ ] 1011 TXT extracts WidgetA ×6, WidgetB ×3, subtotal 3,000.00, tax 0.00, total 3,000.00.
- [ ] 1012 extracts vendor `QuickShip Distributers` (spelling unchanged), raw invoice `INV 1012`, raw names `Widget A`/`WidgetB`/`Gadget X`, raw amount `$3,500.O0`, totals 9,500.00 / 475.00 / 9,975.00.
- [ ] A row with the wrong number of columns becomes an extraction issue, not a shifted value.
