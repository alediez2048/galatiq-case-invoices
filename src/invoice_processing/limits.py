"""Input size limits enforced at intake and during extraction."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 10 * 1024 * 1024
    max_pdf_pages: int = 25
    max_lines: int = 200


DEFAULT_LIMITS = Limits()
