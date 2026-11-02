"""P6-01 campaign 3: malformed input yields specific failure codes, no payment, no traceback."""

import json

import main
import pytest

from invoice_processing.codes import RunStatus, Severity
from invoice_processing.intake import IntakeError
from invoice_processing.service import process_invoice
from tests.robustness import CORPUS, EVAL, OFF, fresh_db, payment_count, query


def corpus(name: str) -> bytes:
    return (CORPUS / name).read_bytes()


JUNK = bytes(range(1, 256)) * 20  # every non-NUL byte value, so it is not valid UTF-8
BIG = 2_000_000
TXT, JSN, CSV, XML, PDF = (
    corpus("invoice_1001.txt"),
    corpus("invoice_1004.json"),
    corpus("invoice_1006.csv"),
    corpus("invoice_1014.xml"),
    corpus("invoice_1011.pdf"),
)
LAUGHS = (
    b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
    b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
    b"]><invoice><x>&c;</x></invoice>"
)
UTF16 = lambda data: data.decode().encode("utf-16")  # noqa: E731

# id: (file name, bytes, expectation). Expectation is ("intake", code) -> IntakeError before any
# run; ("failed", code) -> run failed with that code; ("rejected", None) -> parsed but blocked
# by missing-field blockers, never payable.
CASES = {
    "txt_truncated_header": ("a.txt", TXT[:120], ("rejected", None)),
    "txt_truncated_before_totals": ("a.txt", TXT[: TXT.find(b"Subtotal")], ("rejected", None)),
    "txt_binary_junk_no_nul": ("a.txt", JUNK, ("failed", "txt_decode_error")),
    "txt_binary_junk_with_nul": ("a.txt", b"\x01\x02\x00" + JUNK, ("intake", "format_mismatch")),
    "txt_pdf_bytes": ("a.txt", PDF, ("intake", "format_mismatch")),
    "txt_huge_single_line": ("a.txt", b"A" * BIG, ("rejected", None)),
    "txt_huge_label_value": ("a.txt", b"Vendor: " + b"A" * BIG, ("rejected", None)),
    "txt_latin1": (
        "a.txt",
        TXT.replace(b"Widgets Inc.", b"W\xe9dgets"),
        ("failed", "txt_decode_error"),
    ),
    "txt_mixed_utf8_then_invalid": (
        "a.txt",
        TXT + b"\xff\xfe tail",
        ("failed", "txt_decode_error"),
    ),
    "txt_utf16": ("a.txt", UTF16(TXT), ("intake", "format_mismatch")),
    "json_truncated": ("a.json", JSN[:200], ("failed", "json_invalid")),
    "json_binary_junk": ("a.json", b"{" + JUNK, ("failed", "json_invalid")),
    "json_deeply_nested_arrays": (
        "a.json",
        b"[" * 100_000 + b"]" * 100_000,
        ("failed", "json_invalid"),
    ),
    "json_deeply_nested_objects": (
        "a.json",
        b'{"a":' * 50_000 + b"1" + b"}" * 50_000,
        ("failed", "json_invalid"),
    ),
    "json_huge_single_line": (
        "a.json",
        b'{"invoice_number":"' + b"A" * BIG + b'"}',
        ("rejected", None),
    ),
    "json_latin1": (
        "a.json",
        JSN.replace(b"Precision", b"Pr\xe9cision"),
        ("failed", "json_invalid"),
    ),
    "json_utf16": ("a.json", UTF16(JSN), ("intake", "format_mismatch")),
    "json_xml_content": ("a.json", XML, ("intake", "format_mismatch")),
    "csv_truncated": ("a.csv", CSV[:90], ("rejected", None)),
    "csv_binary_junk": ("a.csv", JUNK, ("failed", "csv_decode_error")),
    "csv_huge_single_field": (
        "a.csv",
        b"field,value\ninvoice_number," + b"A" * BIG + b"\n",
        ("failed", "csv_decode_error"),
    ),
    "csv_latin1": ("a.csv", CSV.replace(b"Acme", b"Acm\xe9"), ("failed", "csv_decode_error")),
    "csv_utf16": ("a.csv", UTF16(CSV), ("intake", "format_mismatch")),
    "xml_truncated": ("a.xml", XML[:300], ("failed", "xml_invalid")),
    "xml_binary_junk": ("a.xml", b"<" + JUNK, ("failed", "xml_invalid")),
    "xml_entity_expansion": ("a.xml", LAUGHS, ("failed", "xml_forbidden_construct")),
    "xml_deeply_nested": (
        "a.xml",
        b"<invoice>" + b"<a>" * 100_000 + b"</a>" * 100_000 + b"</invoice>",
        ("rejected", None),
    ),
    "xml_huge_single_line": (
        "a.xml",
        b"<invoice><x>" + b"A" * BIG + b"</x></invoice>",
        ("rejected", None),
    ),
    "xml_latin1": ("a.xml", XML.replace(b"TechParts", b"T\xe9chParts"), ("failed", "xml_invalid")),
    "xml_utf16": ("a.xml", UTF16(XML), ("intake", "format_mismatch")),
    "pdf_truncated": ("a.pdf", PDF[: len(PDF) // 2], ("failed", "pdf_corrupt")),
    "pdf_header_plus_junk": ("a.pdf", b"%PDF-1.4\n" + JUNK, ("failed", "pdf_corrupt")),
    "pdf_magic_only": ("a.pdf", b"%PDF-", ("failed", "pdf_corrupt")),
    "pdf_not_a_pdf": ("a.pdf", TXT, ("intake", "format_mismatch")),
    "empty_txt": ("a.txt", b"", ("intake", "empty_file")),
    "whitespace_only_json": ("a.json", b"   \n  ", ("intake", "format_mismatch")),
}


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("case", sorted(CASES))
def test_service_outcome_is_specific_and_unpaid(tmp_path, case):
    name, data, (kind, code) = CASES[case]
    db = fresh_db(tmp_path)
    path = write(tmp_path, name, data)
    if kind == "intake":
        with pytest.raises(IntakeError) as exc:
            process_invoice(path, OFF, db, EVAL)
        assert exc.value.code == code
        assert query(db, "SELECT COUNT(*) FROM runs")[0][0] == 0
    elif kind == "failed":
        r = process_invoice(path, OFF, db, EVAL)
        assert r.status is RunStatus.failed and r.errors == [code]
        assert r.receipt is None
        assert query(db, "SELECT status, error_code FROM runs")[0][:] == ("failed", code)
    else:
        r = process_invoice(path, OFF, db, EVAL)
        assert r.status is RunStatus.rejected and r.receipt is None
        assert any(f.severity is Severity.blocker for f in r.findings)
    assert payment_count(db) == 0


@pytest.mark.parametrize("case", sorted(CASES))
def test_cli_never_prints_a_traceback(tmp_path, capsys, case):
    name, data, (kind, code) = CASES[case]
    path = write(tmp_path, name, data)
    argv = [
        f"--invoice_path={path}",
        f"--db={tmp_path / 'cli.db'}",
        f"--events={tmp_path / 'e.jsonl'}",
        "--evaluation-date=2026-01-31",
    ]
    exit_code = main.main(argv)
    out, err = capsys.readouterr()
    assert "Traceback" not in err and "Traceback" not in out
    if kind == "intake":
        assert exit_code == 2 and out == "" and code in err
    elif kind == "failed":
        assert exit_code == 1
        assert json.loads(out)["errors"] == [code]
    else:
        assert exit_code == 0 and json.loads(out)["status"] == "rejected"
    if (tmp_path / "cli.db").exists():
        assert payment_count(tmp_path / "cli.db") == 0


def test_valid_utf8_bom_is_accepted(tmp_path):
    """Control: a BOM is not malformed; it must still process (and pay) normally."""
    db = fresh_db(tmp_path)
    r = process_invoice(write(tmp_path, "bom.txt", b"\xef\xbb\xbf" + TXT), OFF, db, EVAL)
    assert r.status is RunStatus.paid_mock and payment_count(db) == 1


def test_malformed_then_valid_same_db_still_pays_once(tmp_path):
    db = fresh_db(tmp_path)
    for case in ("json_truncated", "txt_binary_junk_no_nul", "pdf_truncated"):
        name, data, _ = CASES[case]
        process_invoice(write(tmp_path, name, data), OFF, db, EVAL)
    good = process_invoice(CORPUS / "invoice_1001.txt", OFF, db, EVAL)
    assert good.status is RunStatus.paid_mock and payment_count(db) == 1
