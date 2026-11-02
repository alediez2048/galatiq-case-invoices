"""Source intake: validate a path and fingerprint its bytes."""

import hashlib
from pathlib import Path

from invoice_processing.codes import SourceFormat
from invoice_processing.limits import DEFAULT_LIMITS, Limits
from invoice_processing.parsers import PARSER_VERSIONS
from invoice_processing.schemas import SourceDocument

SUPPORTED_EXTENSIONS = {".txt", ".json", ".csv", ".xml", ".pdf"}
_BOM = b"\xef\xbb\xbf"
_PDF_MAGIC = b"%PDF-"


class IntakeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _content_matches(fmt: SourceFormat, data: bytes) -> bool:
    head = data.removeprefix(_BOM).lstrip(b" \t\r\n\x0b\x0c")
    if fmt is SourceFormat.pdf:
        return head.startswith(_PDF_MAGIC)
    if fmt is SourceFormat.json:
        return head.startswith((b"{", b"["))
    if fmt is SourceFormat.xml:
        return head.startswith(b"<")
    return not head.startswith(_PDF_MAGIC) and b"\x00" not in data


def read_source(path: str | Path, limits: Limits = DEFAULT_LIMITS) -> tuple[SourceDocument, bytes]:
    path = Path(path)
    if not path.exists():
        raise IntakeError("not_found", f"file not found: {path}")
    if not path.is_file():
        raise IntakeError("not_a_file", f"not a regular file: {path}")
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise IntakeError("unsupported_format", f"unsupported file type: {path.suffix!r}")
    fmt = SourceFormat(ext[1:])
    too_large = IntakeError(
        "file_too_large", f"File exceeds the {limits.max_bytes / 2**20:g} MiB limit."
    )
    try:
        if path.stat().st_size > limits.max_bytes:
            raise too_large
        # Read one byte past the cap so a file that grew after stat() is still refused.
        with path.open("rb") as f:
            data = f.read(limits.max_bytes + 1)
    except OSError as exc:
        raise IntakeError("unreadable", f"could not read file: {exc.strerror or exc}") from exc
    if len(data) > limits.max_bytes:
        raise too_large
    if not data:
        raise IntakeError("empty_file", "The file is empty.")
    if not _content_matches(fmt, data):
        raise IntakeError(
            "format_mismatch",
            f"The file is named {ext} but its content is not {fmt.value.upper()}.",
        )
    content_hash = hashlib.sha256(data).hexdigest()
    source = SourceDocument(
        source_id="src-" + content_hash[:16],
        content_hash=content_hash,
        original_name=path.name,
        format=fmt,
        size_bytes=len(data),
        extracted_text=None,
        parser_version=PARSER_VERSIONS.get(fmt, f"{fmt.value}-unavailable"),
    )
    return source, data
