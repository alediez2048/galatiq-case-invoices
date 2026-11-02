# P2-01 — Input limits and unsupported documents

Phase: 2 · Status: done · Depends on: P1-01 · Requirements: A01, P09

## Context

[Constraints — operational bounds](../contraints.md#proposed-operational-bounds) set 10 MiB per input, 25 PDF pages, and 200 invoice lines. Image-only, encrypted, and corrupt PDFs get explicit unsupported outcomes; OCR is out of scope ([mockup — other essential states](../mockup.md#other-essential-states)).

## Scope

- Extend `intake.py`: size check before reading the whole file; `file_too_large` → `failed` with the limit in the message; no run created beyond the rejection record.
- Format routing by extension, confirmed by content sniffing (`%PDF-` header, JSON parse, XML prolog). A mismatch is `format_mismatch`, not a guess.
- PDF preflight: page count ≤ 25 (`too_many_pages`), encrypted (`pdf_encrypted`), unreadable (`pdf_corrupt`), no extractable text on any page (`pdf_needs_ocr`).
- Line cap: more than 200 extracted lines → `too_many_lines`.
- Each failure has a specific, actionable user message matching the mockup copy, e.g. "This PDF needs OCR, which this prototype does not support."
- Limits are constants in one module so tests can override them.
- Add `pdfplumber` dependency (used here and in P2-07) and refresh the lock.

## Acceptance criteria

- [ ] Generated fixtures under `tests/fixtures/` for: an 11 MiB file, a 26-page PDF, an encrypted PDF, an image-only PDF, a truncated PDF, a `.json` containing XML. Each yields its specific code and no payment.
- [ ] None of these fixtures is committed under `data/invoices/`; originals there are untouched.
- [ ] Limits overridable in tests without monkeypatching internals.
