"""Shared data contracts passed between stages.

Drafts keep raw strings so invalid or missing values survive as evidence; only
normalized invoices carry typed values. Money fields serialize as decimal strings.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from invoice_processing.codes import (
    CritiqueIssue,
    ExecutionMode,
    FindingCode,
    GateOutcome,
    HumanReviewAction,
    InvoiceStatus,
    QueueGroup,
    Recommendation,
    ReviewAction,
    ReviewRefusal,
    RunStatus,
    Severity,
    SourceFormat,
)
from invoice_processing.money import DecimalStr


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


# A free-text local name recorded for audit; not authentication.
ReviewerName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
ReviewReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]


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
    code: FindingCode
    message: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class DraftLine(Contract):
    raw_name: str | None = None
    quantity_raw: str | None = None
    unit_price_raw: str | None = None
    line_total_raw: str | None = None
    note: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class NormalizationEvent(Contract):
    field: str
    raw_value: str | None = None
    normalized_value: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    provenance: str  # "rule:<name>" or "model:<provider>/<model>"


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
    payment_terms_raw: str | None = None
    notes_raw: str | None = None
    tax_rate_fraction_raw: str | None = None  # a fraction such as "0.08" (JSON/XML)
    lines: list[DraftLine] = Field(default_factory=list)
    issues: list[ExtractionIssue] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    field_evidence: dict[str, list[EvidenceRef]] = Field(default_factory=dict)
    normalization_events: list[NormalizationEvent] = Field(default_factory=list)


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
    payment_terms: str | None = None
    notes: str | None = None
    lines: list[LineItem] = Field(default_factory=list)
    stated: StatedTotals = Field(default_factory=StatedTotals)
    computed: ComputedTotals | None = None
    normalization_events: list[NormalizationEvent] = Field(default_factory=list)
    field_evidence: dict[str, list[EvidenceRef]] = Field(default_factory=dict)


class ValidationFinding(Contract):
    code: FindingCode
    severity: Severity
    field: str | None = None
    item: str | None = None
    expected: str | None = None
    observed: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    resolved: bool = False


class HumanReview(Contract):
    invoice_id: str
    version: int
    action: HumanReviewAction
    reviewer: ReviewerName
    reason: ReviewReason
    policy_version: str
    created_at: datetime | None = None


class ApprovalDecision(Contract):
    initial_recommendation: Recommendation
    critique_summary: str | None = None
    critique_issues: list[CritiqueIssue] = Field(default_factory=list)
    revised_recommendation: Recommendation | None = None  # the revision's, when one ran
    final_decision: GateOutcome
    reasons: list[str] = Field(default_factory=list)
    policy_version: str
    mode: ExecutionMode
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    model_calls_used: int = 0
    human_review: HumanReview | None = None


class MockReceipt(Contract):
    receipt_id: str
    amount: DecimalStr
    currency: str
    paid_at: datetime


SUMMARY_MAX_CHARS = 300  # model-written summaries; longer output is model_output_invalid


class RecommendationOutput(Contract):
    """What a live model returns for recommend/revise; provenance is added locally."""

    recommendation: Recommendation
    reasons: list[str]
    cited_codes: list[FindingCode]
    summary: str = Field(max_length=SUMMARY_MAX_CHARS)


class CritiqueOutput(Contract):
    """What a live model returns for critique; provenance is added locally."""

    agrees: bool
    omissions: list[FindingCode]
    high_value: bool
    revised_recommendation: Recommendation | None
    summary: str = Field(max_length=SUMMARY_MAX_CHARS)
    issues: list[CritiqueIssue] = Field(default_factory=list)


class ApprovalRecommendation(RecommendationOutput):
    mode: ExecutionMode
    provider: str
    model: str


class Critique(CritiqueOutput):
    mode: ExecutionMode
    provider: str
    model: str


class SourceExcerpt(Contract):
    location: str  # an evidence location such as "line:9"
    text: str


class ExtractionAssistRequest(Contract):
    """Bounded context for one extraction-assist step: never the whole source by default."""

    issues: list[str]  # finding codes plus the affected field, e.g. "missing_vendor:vendor"
    excerpts: list[SourceExcerpt] = Field(default_factory=list)  # <= excerpt_chars in total
    known_items: list[str] = Field(default_factory=list)
    repair_hint: str | None = None  # set on the single repair attempt: why the output failed


ProposalField = Literal[
    "vendor",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "tax",
    "shipping",
    "total",
]


class FieldProposal(Contract):
    """One model-proposed field value; applied only if `quote` checks out against the source."""

    field: ProposalField
    value: str = Field(max_length=200)
    quote: str = Field(max_length=500)  # verbatim source text supporting the value
    location: str = Field(max_length=200)  # an excerpt location such as "line:9"


class ExtractionProposals(Contract):
    proposals: list[FieldProposal] = Field(default_factory=list, max_length=20)


class GateResult(Contract):
    outcome: GateOutcome
    rule_ids: list[str]
    findings: list[ValidationFinding]  # only the findings the gate adds


class PaymentResult(Contract):
    payment_id: str
    receipt: MockReceipt
    created: bool


class ProcessingResult(Contract):
    run_id: str
    invoice_id: str | None = None
    version: int | None = None
    status: RunStatus
    mode: ExecutionMode
    findings: list[ValidationFinding] = Field(default_factory=list)
    decision: ApprovalDecision | None = None
    receipt: MockReceipt | None = None
    timings_ms: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    source_hash: str | None = None
    prior_run_id: str | None = None
    evaluation_date: date | None = None
    error_message: str | None = None
    model_calls_used: int = 0
    model_calls_budget: int | None = None
    recoverable: bool = False
    next_actions: list[str] = Field(default_factory=list)


class AggregatedItem(Contract):
    item: str
    quantity: DecimalStr
    line_indexes: list[int] = Field(default_factory=list)


# --- Human review (Phase 4) ----------------------------------------------------------------

CORRECTABLE_FIELD = (
    r"^(vendor|invoice_number|invoice_date|due_date|currency"
    r"|stated\.(subtotal|tax|shipping|total)"
    r"|lines\[\d+\]\.(item|quantity|unit_price|line_total))$"
)


class FieldChange(Contract):
    """One corrected field: its new value and where the source shows it."""

    field: str = Field(pattern=CORRECTABLE_FIELD)
    new_value: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    evidence_location: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


class CorrectionRequest(Contract):
    invoice_id: str
    expected_version: int = Field(ge=1)
    changes: list[FieldChange] = Field(min_length=1, max_length=10)
    reason: ReviewReason
    reviewer: ReviewerName

    @model_validator(mode="after")
    def _unique_fields(self) -> "CorrectionRequest":
        fields = [c.field for c in self.changes]
        if len(set(fields)) != len(fields):
            raise ValueError("each field may be corrected at most once per request")
        return self


class Correction(Contract):
    """One recorded field correction, from base_version to resulting_version."""

    invoice_id: str
    base_version: int
    field: str
    old_value: str | None
    new_value: str
    evidence_location: str
    reviewer: ReviewerName
    reason: ReviewReason
    created_at: datetime
    resulting_version: int


class AllowedActions(Contract):
    invoice_id: str
    status: InvoiceStatus
    current_version: int | None
    allowed: list[ReviewAction]
    refused: dict[ReviewAction, ReviewRefusal]


class QueueItem(Contract):
    invoice_id: str
    vendor_name: str | None
    invoice_number: str | None
    total: DecimalStr | None
    currency: str | None
    status: InvoiceStatus
    current_version: int | None
    reason_codes: list[FindingCode]
    actions: AllowedActions


class ReviewQueue(Contract):
    groups: dict[QueueGroup, list[QueueItem]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _every_group(self) -> "ReviewQueue":
        # Every group is present, in QueueGroup order, even when empty.
        self.groups = {g: self.groups.get(g, []) for g in QueueGroup}
        return self


class SupersedeLink(Contract):
    """Links a corrected submission to the invoice it supersedes."""

    invoice_id: str
    reviewer: ReviewerName
    reason: ReviewReason
