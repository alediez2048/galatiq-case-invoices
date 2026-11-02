"""Builders for generated test fixtures; files are created in a caller-supplied directory."""

from pathlib import Path


def oversized_txt(dir: Path, size: int = 11 * 1024 * 1024) -> Path:
    path = dir / "oversized.txt"
    with path.open("wb") as f:
        f.truncate(size)  # sparse: no real disk or memory cost
    return path


def json_containing_xml(dir: Path) -> Path:
    path = dir / "invoice_xml_in_json.json"
    path.write_text('<?xml version="1.0"?>\n<invoice><number>INV-9</number></invoice>\n')
    return path


def txt_with_lines(dir: Path, n: int) -> Path:
    items = "\n".join("  WidgetA    qty: 1    unit price: $1.00" for _ in range(n))
    path = dir / f"invoice_{n}_lines.txt"
    path.write_text(
        "INVOICE\n\n"
        "Vendor: Widgets Inc.\nInvoice Number: INV-1001\n"
        "Date: 2026-01-15\nDue Date: 2026-02-01\n\n"
        f"Items:\n{items}\n\n"
        f"Subtotal: ${n}.00\nTax (0%): $0.00\nTotal Amount: ${n}.00\n\n"
        "Payment Terms: Net 15\n"
    )
    return path
