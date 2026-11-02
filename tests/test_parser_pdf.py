import json
from datetime import date
from pathlib import Path

import pytest

from invoice_processing import seed, storage
from invoice_processing.codes import ExecutionMode, RunStatus
from invoice_processing.intake import read_source
from invoice_processing.limits import DEFAULT_LIMITS, Limits
from invoice_processing.parsers import ExtractionError, parse_document
from invoice_processing.parsers.pdf import extract_pdf_text
from invoice_processing.parsers.txt import parse_txt
from invoice_processing.service import process_invoice
from invoice_processing.storage import connect
from tests import fixture_factory as ff


def pdf(name):
    return parse_document(*read_source(f"data/invoices/{name}"), DEFAULT_LIMITS)


def seeded_db(tmp_path) -> Path:
    db = tmp_path / "db.sqlite"
    c = connect(db)
    storage.init_schema(c)
    seed.seed_inventory(c)
    c.close()
    return db


@pytest.mark.parametrize("stem", ["invoice_1011", "invoice_1012", "invoice_1013"])
def test_snapshot(stem):
    pages = extract_pdf_text(Path(f"data/invoices/{stem}.pdf").read_bytes(), DEFAULT_LIMITS)
    assert "\n\f\n".join(pages) == Path(f"tests/fixtures/pdf_text/{stem}.txt").read_text()


def test_1011_pdf_total_only():
    d = pdf("invoice_1011.pdf").draft
    assert [(ln.raw_name, ln.quantity_raw) for ln in d.lines] == [
        ("WidgetA", "6"),
        ("WidgetB", "3"),
    ]
    assert d.total_raw == "$3,000.00" and d.subtotal_raw is None and d.tax_raw is None
    assert d.lines[0].evidence[0].location.startswith("page:1,line:")


def test_1012_pdf_matches_txt():
    t = parse_txt(*read_source("data/invoices/invoice_1012.txt"))
    p = pdf("invoice_1012.pdf").draft
    fields = (
        "vendor_raw",
        "invoice_number_raw",
        "invoice_date_raw",
        "due_date_raw",
        "subtotal_raw",
        "tax_rate_raw",
        "tax_raw",
        "total_raw",
        "payment_terms_raw",
        "notes_raw",
    )
    assert [getattr(p, f) for f in fields] == [getattr(t, f) for f in fields]

    def key(d):
        return [
            (ln.raw_name, ln.quantity_raw, ln.unit_price_raw, ln.line_total_raw) for ln in d.lines
        ]

    assert key(p) == key(t)


def test_1013_pdf():
    d = pdf("invoice_1013.pdf").draft
    assert len(d.lines) == 8 and d.invoice_number_raw == "INV-1013"
    assert (d.invoice_date_raw, d.due_date_raw) == ("2026-01-24", "2026-03-24")
    assert [ln.note for ln in d.lines][3:] == [
        "Volume discount",
        "Volume discount",
        "Expedited",
        "Replacement",
        "Sample",
    ]
    assert (d.subtotal_raw, d.tax_rate_raw, d.tax_raw, d.total_raw) == (
        "$21,040.00",
        "7",
        "$1,472.80",
        "$22,562.80",
    )
    assert d.currency_raw is None and d.payment_terms_raw == "Net 60"


@pytest.mark.parametrize(
    "build,code",
    [
        (lambda d: ff.pdf_pages(d, 26), "too_many_pages"),
        (ff.image_only_pdf, "pdf_needs_ocr"),
        (ff.encrypted_pdf, "pdf_encrypted"),
        (ff.truncated_pdf, "pdf_corrupt"),
    ],
)
def test_preflight_failures_fail_the_run_without_payment(tmp_path, build, code):
    result = process_invoice(
        build(tmp_path), ExecutionMode.offline, seeded_db(tmp_path), date(2026, 1, 31)
    )
    assert result.status is RunStatus.failed and result.errors == [code] and result.error_message
    assert result.receipt is None


def test_empty_password_encryption_is_readable(tmp_path):
    src = ff.encrypted_pdf(tmp_path, user_password="")
    d = parse_document(*read_source(src), DEFAULT_LIMITS).draft
    assert d.total_raw == "$3,000.00"


def test_page_limit_overridable():
    with pytest.raises(ExtractionError) as e:
        extract_pdf_text(
            Path("data/invoices/invoice_1011.pdf").read_bytes(), Limits(max_pdf_pages=0)
        )
    assert e.value.code == "too_many_pages"


def test_extracted_text_stored_but_never_logged(tmp_path):
    db = seeded_db(tmp_path)
    log = tmp_path / "events.jsonl"
    import logging

    logger = logging.getLogger("test_pdf_events")
    logger.propagate = False
    handler = logging.FileHandler(log)
    logger.addHandler(handler)
    try:
        r = process_invoice(
            "data/invoices/invoice_1011.pdf",
            ExecutionMode.offline,
            db,
            date(2026, 1, 31),
            events=logger,
        )
    finally:
        logger.removeHandler(handler)
        handler.close()
    c = connect(db)
    try:
        text = c.execute("SELECT extracted_text FROM sources").fetchone()[0]
        assert "Summit Manufacturing Co." in text and "Unit Price" in text
        payloads = [json.dumps(e, default=str) for e in _audit(c, r.run_id)]
    finally:
        c.close()
    for blob in [*payloads, log.read_text()]:
        assert not ("Summit Manufacturing Co." in blob and "Unit Price" in blob)


def _audit(conn, run_id):
    from invoice_processing import ledger

    return ledger.list_audit_events(conn, run_id)
