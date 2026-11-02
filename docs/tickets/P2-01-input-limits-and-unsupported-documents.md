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

- [x] Generated fixtures under `tests/fixtures/` for: an 11 MiB file, a 26-page PDF, an encrypted PDF, an image-only PDF, a truncated PDF, a `.json` containing XML. Each yields its specific code and no payment. (tests/test_intake.py::test_oversized_file_rejected_before_read, tests/test_intake.py::test_json_containing_xml_is_format_mismatch, tests/test_parser_pdf.py::test_preflight_failures_fail_the_run_without_payment; built in `tmp_path` by tests/fixture_factory.py per plan decision 3)
- [x] None of these fixtures is committed under `data/invoices/`; originals there are untouched. (tests/fixture_factory.py writes only to `tmp_path`; tests/test_acceptance.py::test_every_fixture_has_a_case)
- [x] Limits overridable in tests without monkeypatching internals. (tests/test_intake.py::test_limit_overridable, tests/test_parser_pdf.py::test_page_limit_overridable)
