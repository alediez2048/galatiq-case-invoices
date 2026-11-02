# P2-06 — Hardened XML parser

Phase: 2 · Status: done · Depends on: P1-01 · Requirements: A01, P01

## Context

INV-1014 is XML: `<header>` with invoice number, vendor, dates, and explicit `<currency>EUR</currency>`; `<line_items>/<item>` with `name`, `quantity`, `unit_price`; `<totals>` with subtotal, tax rate, tax amount, total. External entity resolution must be disabled ([constraints — security](../contraints.md#security-and-trust-boundaries)).

## Scope

- Add `defusedxml`; `parsers/xml_parser.py` uses `defusedxml.ElementTree`.
- Map elements into `InvoiceDraft` with element-path evidence (`/invoice/line_items/item[2]/quantity`).
- Element text parsed straight to `Decimal`.
- Missing or repeated singleton elements → extraction issues.
- DTDs, entities, and external references → `xml_forbidden_construct` failure.

## Acceptance criteria

- [ ] 1014 yields vendor `TechParts International`, currency `EUR` (explicit, not assumed), WidgetA ×4 @ 225.00, WidgetB ×6 @ 475.00, subtotal 3,750.00, tax 375.00 at 10%, total 4,125.00.
- [ ] A billion-laughs test document and an external-entity test document are both refused.
- [ ] No network or file access occurs while parsing (network guard from P1-10 active).
