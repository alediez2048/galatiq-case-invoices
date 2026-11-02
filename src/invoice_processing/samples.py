"""Sample invoice listing. Labels describe the input, never the expected outcome."""

import re
from pathlib import Path

from pydantic import BaseModel

from invoice_processing.intake import SUPPORTED_EXTENSIONS

LABELS: dict[str, str] = {
    "invoice_1001.txt": "Clean invoice",
    "invoice_1002.txt": "Messy formatting",
    "invoice_1003.txt": "Urgent payment request",
    "invoice_1004.json": "JSON invoice",
    "invoice_1004_revised.json": "Revised invoice",
    "invoice_1005.json": "Large quantities",
    "invoice_1006.csv": "Key-value CSV",
    "invoice_1007.csv": "Conflicting totals",
    "invoice_1008.txt": "Email-style text",
    "invoice_1009.json": "Missing fields",
    "invoice_1010.txt": "Repeated items",
    "invoice_1011.txt": "Text invoice (also supplied as PDF)",
    "invoice_1011.pdf": "PDF invoice (also supplied as text)",
    "invoice_1012.txt": "Irregular text layout (also supplied as PDF)",
    "invoice_1012.pdf": "PDF invoice (also supplied as text)",
    "invoice_1013.json": "Many line items",
    "invoice_1013.pdf": "PDF with many line items",
    "invoice_1014.xml": "Unsupported currency",
    "invoice_1015.csv": "Table CSV with totals",
    "invoice_1016.json": "Item not in the catalog",
}
_NUMBER = re.compile(r"invoice_(\d+)")


class Sample(BaseModel):
    name: str
    label: str
    invoice_number: str | None
    format: str
    size_bytes: int


def list_samples(samples_dir: Path) -> list[Sample]:
    if not samples_dir.is_dir():
        return []
    out: list[Sample] = []
    for path in sorted(samples_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        m = _NUMBER.match(path.stem)
        out.append(
            Sample(
                name=path.name,
                label=LABELS.get(path.name, "Invoice file"),
                invoice_number=f"INV-{m.group(1)}" if m else None,
                format=path.suffix.lower()[1:],
                size_bytes=path.stat().st_size,
            )
        )
    return out


def resolve_sample(samples_dir: Path, name: str) -> Path | None:
    """The sample file for a bare basename, or None. Anything with a separator is refused."""
    if not name or name != Path(name).name or "\\" in name or name.startswith("."):
        return None
    path = samples_dir / name
    return path if path.is_file() else None
