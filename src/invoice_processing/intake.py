"""Source intake: validate a path and fingerprint its bytes."""

import hashlib
from pathlib import Path

from invoice_processing.codes import SourceFormat
from invoice_processing.parsers.txt import PARSER_VERSION
from invoice_processing.schemas import SourceDocument

SUPPORTED_EXTENSIONS = {".txt"}


class IntakeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def read_source(path: str | Path) -> tuple[SourceDocument, bytes]:
    path = Path(path)
    if not path.exists():
        raise IntakeError("not_found", f"file not found: {path}")
    if not path.is_file():
        raise IntakeError("not_a_file", f"not a regular file: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise IntakeError("unsupported_format", f"unsupported file type: {path.suffix!r}")
    data = path.read_bytes()
    content_hash = hashlib.sha256(data).hexdigest()
    source = SourceDocument(
        source_id="src-" + content_hash[:16],
        content_hash=content_hash,
        original_name=path.name,
        format=SourceFormat.txt,
        size_bytes=len(data),
        extracted_text=None,
        parser_version=PARSER_VERSION,
    )
    return source, data
