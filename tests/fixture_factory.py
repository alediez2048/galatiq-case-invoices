"""Builders for generated test fixtures; files are created in a caller-supplied directory."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter

SOURCE_PDF = Path("data/invoices/invoice_1011.pdf")


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


def pdf_pages(dir: Path, n: int) -> Path:
    writer = PdfWriter()
    for _ in range(n):
        writer.add_blank_page(612, 792)
    path = dir / f"blank_{n}_pages.pdf"
    with path.open("wb") as f:
        writer.write(f)
    return path


def image_only_pdf(dir: Path) -> Path:
    return pdf_pages(dir, 1)


def encrypted_pdf(dir: Path, user_password: str = "secret") -> Path:
    writer = PdfWriter(clone_from=PdfReader(SOURCE_PDF))
    writer.encrypt(user_password=user_password, owner_password="o", algorithm="RC4-128")
    path = dir / "encrypted.pdf"
    with path.open("wb") as f:
        writer.write(f)
    return path


def truncated_pdf(dir: Path) -> Path:
    path = dir / "truncated.pdf"
    path.write_bytes(SOURCE_PDF.read_bytes()[:600])
    return path
