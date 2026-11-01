"""Builders for NormalizedInvoice test data, with values taken from the supplied fixtures."""

from datetime import date
from decimal import Decimal

from invoice_processing.codes import FindingCode
from invoice_processing.schemas import LineItem, NormalizedInvoice, StatedTotals, ValidationFinding


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def line(
    item: str | None, qty: str | None, price: str | None, total: str | None = None
) -> LineItem:
    return LineItem(item=item, quantity=_dec(qty), unit_price=_dec(price), line_total=_dec(total))


def invoice(
    *,
    lines: list[LineItem],
    vendor: str | None = "Vendor",
    number: str | None = "INV-1",
    currency: str | None = "USD",
    due: str | None = "2026-02-01",
    subtotal: str | None = None,
    tax_rate: str | None = None,
    tax: str | None = None,
    shipping: str | None = None,
    total: str | None = None,
) -> NormalizedInvoice:
    return NormalizedInvoice(
        source_id="test-source",
        vendor_name=vendor,
        vendor_key=vendor.strip().lower() if isinstance(vendor, str) else None,
        invoice_number=number,
        currency=currency,
        due_date=None if due is None else date.fromisoformat(due),
        lines=lines,
        stated=StatedTotals(
            subtotal=_dec(subtotal),
            tax_rate=_dec(tax_rate),
            tax=_dec(tax),
            shipping=_dec(shipping),
            total=_dec(total),
        ),
    )


def inv_1001() -> NormalizedInvoice:
    return invoice(
        lines=[line("WidgetA", "10", "250.00"), line("WidgetB", "5", "500.00")],
        vendor="Widgets Inc.",
        number="INV-1001",
        subtotal="5000.00",
        tax_rate="0",
        tax="0.00",
        total="5000.00",
    )


def inv_1009() -> NormalizedInvoice:
    return invoice(
        lines=[line("WidgetA", "-5", "250.00"), line("WidgetB", "2", "500.00")],
        vendor=None,
        number="INV-1009",
        due=None,
        subtotal="1000.00",
        tax_rate="0.0",
        tax="0.00",
        total="-250.00",
    )


def inv_1013() -> NormalizedInvoice:
    rows = [
        ("WidgetA", "15", "250.00", "3750.00"),
        ("WidgetB", "10", "500.00", "5000.00"),
        ("GadgetX", "5", "750.00", "3750.00"),
        ("WidgetA", "5", "240.00", "1200.00"),
        ("WidgetB", "8", "480.00", "3840.00"),
        ("GadgetX", "3", "750.00", "2250.00"),
        ("WidgetA", "2", "250.00", "500.00"),
        ("GadgetX", "1", "750.00", "750.00"),
    ]
    return invoice(
        lines=[line(*row) for row in rows],
        vendor="Atlas Industrial Supply",
        number="INV-1013",
        due="2026-03-24",
        subtotal="21040.00",
        tax_rate="0.07",
        tax="1472.80",
        total="22562.80",
    )


def inv_1010() -> NormalizedInvoice:
    return invoice(
        lines=[
            line("WidgetA", "8", "250.00"),
            line("WidgetB", "4", "500.00"),
            line("GadgetX", "2", "750.00"),
            line("WidgetA", "4", "300.00"),
        ],
        vendor="Consolidated Materials Group",
        number="INV-1010",
        due="2026-02-26",
        subtotal="6700.00",
        tax="335.00",
        shipping="150.00",
        total="7185.00",
    )


def codes(findings: list[ValidationFinding]) -> list[FindingCode]:
    return [f.code for f in findings]
