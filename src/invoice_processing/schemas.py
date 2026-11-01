"""Shared data contracts passed between stages.

Drafts keep raw strings so invalid or missing values survive as evidence; only
normalized invoices carry typed values. Money fields serialize as decimal strings.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from invoice_processing.codes import (
    ExecutionMode,
    FindingCode,
    GateOutcome,
    Recommendation,
    RunStatus,
    Severity,
    SourceFormat,
)
from invoice_processing.money import DecimalStr


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(Contract):
    source_id: str
    location: str  # e.g. "line:9", "row:3", "page:1,line:4", "$.line_items[2].quantity"
    snippet: str | None = None


class SourceDocument(Contract):
    source_id: str
    content_hash: str
    original_name: str
    format: SourceFormat
    size_bytes: int
    page_count: int | None = None
    extracted_text: str | None = None
    parser_version: str


class ExtractionIssue(Contract):
    code: str
    message: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class DraftLine(Contract):
    raw_name: str | None = None
    quantity_raw: str | None = None
    unit_price_raw: str | None = None
    line_total_raw: str | None = None
    note: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class InvoiceDraft(Contract):
    source_id: str
    vendor_raw: str | None = None
    invoice_number_raw: str | None = None
    revision_raw: str | None = None
    invoice_date_raw: str | None = None
    due_date_raw: str | None = None
    currency_raw: str | None = None
    subtotal_raw: str | None = None
    tax_rate_raw: str | None = None
    tax_raw: str | None = None
    shipping_raw: str | None = None
    total_raw: str | None = None
    lines: list[DraftLine] = Field(default_factory=list)
    issues: list[ExtractionIssue] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class NormalizationEvent(Contract):
    field: str
    raw_value: str | None = None
    normalized_value: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    provenance: str  # "rule:<name>" or "model:<provider>/<model>"


class LineItem(Contract):
    item: str | None = None
    quantity: DecimalStr | None = None
    unit_price: DecimalStr | None = None
    line_total: DecimalStr | None = None
    note: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class StatedTotals(Contract):
    subtotal: DecimalStr | None = None
    tax_rate: DecimalStr | None = None
    """A fraction (0.07), not a percent. Normalization converts "TAX (7%)" to 0.07."""
    tax: DecimalStr | None = None
    shipping: DecimalStr | None = None
    total: DecimalStr | None = None


class ComputedTotals(Contract):
    line_totals: list[DecimalStr | None] = Field(default_factory=list)
    subtotal: DecimalStr | None = None
    tax: DecimalStr | None = None
    shipping: DecimalStr | None = None
    total: DecimalStr | None = None


class NormalizedInvoice(Contract):
    source_id: str
    vendor_name: str | None = None
    vendor_key: str | None = None
    invoice_number: str | None = None
    invoice_number_key: str | None = None
    revision: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    lines: list[LineItem] = Field(default_factory=list)
    stated: StatedTotals = Field(default_factory=StatedTotals)
    computed: ComputedTotals | None = None
    normalization_events: list[NormalizationEvent] = Field(default_factory=list)


class ValidationFinding(Contract):
    code: FindingCode
    severity: Severity
    field: str | None = None
    item: str | None = None
    expected: str | None = None
    observed: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    resolved: bool = False


class ApprovalDecision(Contract):
    initial_recommendation: Recommendation
    critique_summary: str | None = None
    revised_recommendation: Recommendation | None = None
    final_decision: GateOutcome
    reasons: list[str] = Field(default_factory=list)
    policy_version: str
    mode: ExecutionMode
    provider: str | None = None
    model: str | None = None


class MockReceipt(Contract):
    receipt_id: str
    amount: DecimalStr
    currency: str
    paid_at: datetime


class ProcessingResult(Contract):
    run_id: str
    invoice_id: str | None = None
    status: RunStatus
    mode: ExecutionMode
    findings: list[ValidationFinding] = Field(default_factory=list)
    decision: ApprovalDecision | None = None
    receipt: MockReceipt | None = None
    timings_ms: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class AggregatedItem(Contract):
    item: str
    quantity: DecimalStr
    line_indexes: list[int] = Field(default_factory=list)
