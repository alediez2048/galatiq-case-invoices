import os
from pathlib import Path

import pytest

from invoice_processing.codes import SourceFormat
from invoice_processing.intake import SUPPORTED_EXTENSIONS, IntakeError, read_source
from invoice_processing.limits import Limits
from invoice_processing.parsers import PARSER_VERSIONS
from invoice_processing.parsers.txt import PARSER_VERSION
from tests import fixture_factory as ff

FIXTURE = Path("data/invoices/invoice_1001.txt")


def test_read_source_describes_the_file():
    source, data = read_source(FIXTURE)
    assert data == FIXTURE.read_bytes()
    assert source.content_hash and len(source.content_hash) == 64
    assert source.source_id == "src-" + source.content_hash[:16]
    assert source.format == SourceFormat.txt
    assert source.parser_version == PARSER_VERSION
    assert source.original_name == "invoice_1001.txt"
    assert source.size_bytes == len(data)
    assert source.extracted_text is None


def test_supported_extensions():
    assert {".txt", ".json", ".csv", ".xml", ".pdf"} == SUPPORTED_EXTENSIONS


def _write(path):
    path.write_text("x")
    return path


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda d: d / "missing.txt", "not_found"),
        (lambda d: (d / "dir.txt").mkdir() or d / "dir.txt", "not_a_file"),
        (lambda d: _write(d / "a.docx"), "unsupported_format"),
    ],
)
def test_intake_errors(tmp_path, make, code):
    with pytest.raises(IntakeError) as e:
        read_source(make(tmp_path))
    assert e.value.code == code


def test_uppercase_extension_and_spaces_accepted(tmp_path):
    p = tmp_path / "my invoice 1001.TXT"
    p.write_bytes(FIXTURE.read_bytes())
    assert read_source(p)[0].content_hash == read_source(FIXTURE)[0].content_hash


def _code(path, **kw):
    with pytest.raises(IntakeError) as e:
        read_source(path, **kw)
    return e.value.code, str(e.value)


def test_oversized_file_rejected_before_read(tmp_path):
    assert _code(ff.oversized_txt(tmp_path)) == ("file_too_large", "File exceeds the 10 MiB limit.")


def test_limit_overridable(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("INVOICE\n")
    assert _code(p, limits=Limits(max_bytes=4))[0] == "file_too_large"


def test_json_containing_xml_is_format_mismatch(tmp_path):
    code, msg = _code(ff.json_containing_xml(tmp_path))
    assert code == "format_mismatch"
    assert msg == "The file is named .json but its content is not JSON."


@pytest.mark.parametrize("name,fmt", [("x.JSON", SourceFormat.json), ("x.Xml", SourceFormat.xml)])
def test_extension_case_insensitive(tmp_path, name, fmt):
    p = tmp_path / name
    p.write_text("{}" if fmt is SourceFormat.json else "<a/>")
    assert read_source(p)[0].format is fmt


def test_empty_file(tmp_path):
    p = tmp_path / "e.txt"
    p.write_bytes(b"")
    assert _code(p)[0] == "empty_file"


def test_pdf_header_required(tmp_path):
    p = tmp_path / "f.pdf"
    p.write_text("hello")
    assert _code(p)[0] == "format_mismatch"


def test_sniff_skips_bom_and_whitespace(tmp_path):
    p = tmp_path / "b.json"
    p.write_bytes(b"\xef\xbb\xbf  \n[1]")
    assert read_source(p)[0].format is SourceFormat.json


@pytest.mark.parametrize("data", [b"%PDF-1.4 x", b"abc\x00def"])
def test_txt_rejects_pdf_and_nul_bytes(tmp_path, data):
    p = tmp_path / "t.txt"
    p.write_bytes(data)
    assert _code(p) == (
        "format_mismatch",
        "The file is named .txt but its content is not TXT.",
    )


@pytest.mark.parametrize("fmt", list(SourceFormat))
def test_parser_version_comes_from_registry(fmt):
    sample = next(sorted(Path("data/invoices").glob(f"*.{fmt.value}")).__iter__())
    source, _ = read_source(sample)
    assert source.parser_version == PARSER_VERSIONS[fmt]


def test_all_supplied_files_pass_intake():
    for p in sorted(Path("data/invoices").iterdir()):
        source, _ = read_source(p)
        assert source.format.value == p.suffix[1:].lower()


def test_file_growing_after_stat_is_still_too_large(tmp_path, monkeypatch):
    # The size check must hold for the bytes actually read, not only for stat().
    p = tmp_path / "grow.txt"
    p.write_text("INVOICE 1001\n")
    real_stat = Path.stat

    def stale_stat(self, *a, **k):
        st = real_stat(self, *a, **k)
        if self.name != p.name:
            return st
        return os.stat_result((*st[:6], 1, *st[7:10]))

    monkeypatch.setattr(Path, "stat", stale_stat)
    assert _code(p, limits=Limits(max_bytes=4))[0] == "file_too_large"
    assert read_source(p, limits=Limits(max_bytes=13))[1] == b"INVOICE 1001\n"
