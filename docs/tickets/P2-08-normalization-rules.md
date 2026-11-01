# P2-08 — Evidence-backed normalization: items, OCR artifacts, identity

Phase: 2 · Status: todo · Depends on: P2-02, P2-03 · Requirements: P04, P03

## Context

Corrections must be traceable and bounded; missing vendors, totals, or dates are never fabricated, and ambiguous changes go to review ([requirements — P04](../requirements.md#project-requirements-added-for-a-reliable-mvp), [constraints — dataset limitations](../contraints.md#dataset-and-business-limitations)). Identity normalization must be conservative: case/whitespace and evidenced invoice-number formatting, no fuzzy vendor merging ([system design](../systemsdesign.md#persistence-and-transaction-boundaries)).

## Scope

Rules in `normalize.py`, each emitting a `NormalizationEvent` (raw, normalized, evidence, `rule:<name>`):

- **Item canonicalization** against inventory names:
  - Whitespace-insensitive exact match: `Widget A` → `WidgetA`, `Gadget X` → `GadgetX` (`rule:item_spacing`).
  - Explicit parenthetical qualifier: `WidgetA (rush order)` → `WidgetA`, qualifier kept as a line note (`rule:item_qualifier`).
  - No edit-distance or fuzzy matching. `WidgetC`, `SuperGizmo`, `MegaSprocket` stay as-is and fail inventory as unknown.
- **OCR digit artifacts**: letter `O` → `0` only inside a token that is otherwise a valid number or year (`3,500.O0`, `2O26`) (`rule:ocr_digit`). Also verify the corrected amount against qty × price when available; if it disagrees, emit `ambiguous_normalization` → `needs_review`.
- **Invoice-number identity key**: uppercase, remove separators, strip a leading `INV` (`INV 1012`, `INV-1012` → `1012`; `1002` → `1002`). Display value keeps the source text. Record `rule:invoice_number_format`.
- **Vendor key**: case-fold and collapse whitespace only. `QuickShip Distributers` is not spell-corrected; `(formerly FastShip Ltd.)` does not create an alias.
- Any change that a rule cannot fully justify is not applied and emits `ambiguous_normalization` (severity `review`).

## Acceptance criteria

- [ ] 1010 canonicalizes to WidgetA ×8 and ×4 (aggregating to 12), WidgetB ×4, GadgetX ×2.
- [ ] 1012 canonicalizes to WidgetA ×12, WidgetB ×7, GadgetX ×4, line total 3,500.00, with one event per change.
- [ ] 1016's `WidgetC` is not mapped to any inventory item.
- [ ] A constructed `$3,5O0.00` on a line where qty × price = 3,000.00 yields `ambiguous_normalization`, not a silent fix.
