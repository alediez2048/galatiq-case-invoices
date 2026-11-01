from pathlib import Path

import pytest

from invoice_processing.codes import SourceFormat
from invoice_processing.intake import SUPPORTED_EXTENSIONS, IntakeError, read_source
from invoice_processing.parsers.txt import PARSER_VERSION

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
    assert {".txt"} == SUPPORTED_EXTENSIONS


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
