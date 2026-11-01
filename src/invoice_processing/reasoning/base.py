"""Reasoning provider seam. Live Grok plugs in here in Phase 3."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from invoice_processing.codes import ExecutionMode
from invoice_processing.schemas import (
    ApprovalRecommendation,
    Critique,
    InvoiceDraft,
    NormalizedInvoice,
    ValidationFinding,
)


@dataclass(frozen=True)
class PolicyContext:
    policy_version: str
    high_value_threshold: Decimal


class ReasoningProvider(Protocol):
    mode: ExecutionMode
    provider: str
    model: str

    def recommend(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        policy: PolicyContext,
    ) -> ApprovalRecommendation: ...

    def critique(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        recommendation: ApprovalRecommendation,
        policy: PolicyContext,
    ) -> Critique: ...

    def assist_extraction(self, source_text: str, draft: InvoiceDraft) -> InvoiceDraft: ...
