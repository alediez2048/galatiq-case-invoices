"""Deterministic offline stand-in for the reasoning model. Imports no model SDK."""

from invoice_processing.codes import ExecutionMode, FindingCode, Recommendation, Severity
from invoice_processing.reasoning.base import PolicyContext
from invoice_processing.schemas import (
    ApprovalRecommendation,
    Critique,
    InvoiceDraft,
    NormalizedInvoice,
    ValidationFinding,
)

_PREFIX = "offline simulation: "
_CITED = {Severity.blocker, Severity.review}


def _cited_codes(findings: list[ValidationFinding]) -> list[FindingCode]:
    codes: list[FindingCode] = []
    for f in findings:
        if f.severity in _CITED and f.code not in codes:
            codes.append(f.code)
    return codes


def _rule(findings: list[ValidationFinding]) -> Recommendation:
    severities = {f.severity for f in findings}
    if Severity.blocker in severities:
        return Recommendation.reject
    if Severity.review in severities:
        return Recommendation.review
    return Recommendation.approve


class OfflineSimulator:
    mode = ExecutionMode.offline
    provider = "offline"
    model = "simulated"

    def recommend(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        policy: PolicyContext,
    ) -> ApprovalRecommendation:
        rec = _rule(findings)
        cited = _cited_codes(findings)
        return ApprovalRecommendation(
            recommendation=rec,
            reasons=[c.value for c in cited],
            cited_codes=cited,
            summary=f"{_PREFIX}{rec.value} based on {len(cited)} blocking or review finding(s)",
            mode=self.mode,
            provider=self.provider,
            model=self.model,
        )

    def critique(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        recommendation: ApprovalRecommendation,
        policy: PolicyContext,
    ) -> Critique:
        omissions = [c for c in _cited_codes(findings) if c not in recommendation.cited_codes]
        expected = _rule(findings)
        consistent = (recommendation.recommendation is Recommendation.reject) == (
            expected is Recommendation.reject
        )
        agrees = not omissions and consistent
        total = invoice.stated.total
        high_value = total is not None and total > policy.high_value_threshold
        return Critique(
            agrees=agrees,
            omissions=omissions,
            high_value=high_value,
            revised_recommendation=None if agrees else expected,
            summary=(
                f"{_PREFIX}critique {'agrees' if agrees else 'disagrees'}; "
                f"{len(omissions)} omission(s); high_value={high_value}"
            ),
            mode=self.mode,
            provider=self.provider,
            model=self.model,
        )

    def assist_extraction(self, source_text: str, draft: InvoiceDraft) -> InvoiceDraft:
        return draft
