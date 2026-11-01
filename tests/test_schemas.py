from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoice_processing import schemas
from invoice_processing.codes import FindingCode, Severity

CONTRACTS = [
    schemas.EvidenceRef,
    schemas.SourceDocument,
    schemas.InvoiceDraft,
    schemas.NormalizationEvent,
    schemas.NormalizedInvoice,
    schemas.ValidationFinding,
    schemas.ApprovalDecision,
    schemas.ProcessingResult,
    schemas.AggregatedItem,
]


def inv_1009_draft() -> schemas.InvoiceDraft:
    return schemas.InvoiceDraft(
        source_id="src-1009",
        vendor_raw="",
        invoice_number_raw="INV-1009",
        invoice_date_raw="2026-01-15",
        due_date_raw=None,
        currency_raw="USD",
        subtotal_raw="1000.00",
        tax_rate_raw="0.0",
        tax_raw="0.00",
        total_raw="-250.00",
        lines=[
            schemas.DraftLine(raw_name="WidgetA", quantity_raw="-5", unit_price_raw="250.00"),
            schemas.DraftLine(raw_name="WidgetB", quantity_raw="2", unit_price_raw="500.00"),
        ],
    )


def test_draft_holds_invalid_data_without_raising():
    draft = inv_1009_draft()
    assert draft.lines[0].quantity_raw == "-5"
    assert draft.total_raw == "-250.00"


@pytest.mark.parametrize("model", CONTRACTS)
def test_json_schema_generates(model):
    assert model.model_json_schema()["title"] == model.__name__


def test_normalized_invoice_round_trip_keeps_decimal_strings():
    inv = schemas.NormalizedInvoice(
        source_id="s",
        currency="USD",
        due_date=date(2026, 2, 1),
        lines=[
            schemas.LineItem(item="WidgetA", quantity=Decimal("10"), unit_price=Decimal("250.00"))
        ],
        stated=schemas.StatedTotals(total=Decimal("22512.80")),
    )
    dumped = inv.model_dump_json()
    assert '"total":"22512.80"' in dumped
    assert schemas.NormalizedInvoice.model_validate_json(dumped) == inv


def test_finding_round_trip():
    f = schemas.ValidationFinding(
        code=FindingCode.total_mismatch,
        severity=Severity.blocker,
        field="total",
        expected="22512.80",
        observed="22562.80",
    )
    assert schemas.ValidationFinding.model_validate_json(f.model_dump_json()) == f


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        schemas.EvidenceRef(source_id="s", location="line:1", bogus=1)


SAMPLES = [
    schemas.EvidenceRef(source_id="s", location="line:1"),
    schemas.ExtractionIssue(code="unreadable", message="m"),
    schemas.DraftLine(raw_name="WidgetA", quantity_raw="1"),
    schemas.LineItem(item="WidgetA", quantity=Decimal("1"), unit_price=Decimal("1.00")),
    schemas.StatedTotals(tax_rate=Decimal("0.07"), total=Decimal("10.70")),
    schemas.ComputedTotals(line_totals=[Decimal("10.00"), None], total=Decimal("10.70")),
    schemas.MockReceipt(
        receipt_id="r",
        amount=Decimal("5000.00"),
        currency="USD",
        paid_at=datetime(2026, 1, 31, tzinfo=UTC),
    ),
    schemas.ApprovalDecision(
        initial_recommendation="approve",
        final_decision="approved",
        policy_version="p1",
        mode="offline",
    ),
]


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: type(s).__name__)
def test_every_contract_round_trips(sample):
    model = type(sample)
    assert model.model_json_schema()["title"] == model.__name__
    assert model.model_validate_json(sample.model_dump_json()) == sample


def test_approval_decision_rejects_unknown_recommendation_or_outcome():
    base = dict(policy_version="p1", mode="offline")
    with pytest.raises(ValidationError):
        schemas.ApprovalDecision(initial_recommendation="aprove", final_decision="approved", **base)
    with pytest.raises(ValidationError):
        schemas.ApprovalDecision(initial_recommendation="approve", final_decision="paid", **base)
