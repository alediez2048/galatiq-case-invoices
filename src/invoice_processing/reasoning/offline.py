"""Deterministic offline stand-in for the reasoning model. Imports no model SDK.

It never charges or records anything on the session it receives (offline uses no budget).
"""

from invoice_processing.codes import ExecutionMode, FindingCode, Recommendation, Severity
from invoice_processing.reasoning.base import PolicyContext
from invoice_processing.reasoning.session import ModelSession
from invoice_processing.schemas import (
    ApprovalRecommendation,
    Critique,
    ExtractionAssistRequest,
    ExtractionProposals,
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


def _high_value(invoice: NormalizedInvoice, policy: PolicyContext) -> bool:
    total = invoice.stated.total
    return total is not None and total > policy.high_value_threshold


def _threshold_note(invoice: NormalizedInvoice, policy: PolicyContext) -> str:
    if not _high_value(invoice, policy):
        return ""
    return f"; total above the {policy.high_value_threshold} high-value threshold"


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
    prompt_version = None
    extract_prompt_version = None
    excerpt_chars = 0  # offline sends no source text anywhere

    def recommend(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        policy: PolicyContext,
        session: ModelSession,
    ) -> ApprovalRecommendation:
        rec = _rule(findings)
        cited = _cited_codes(findings)
        return ApprovalRecommendation(
            recommendation=rec,
            reasons=[c.value for c in cited],
            cited_codes=cited,
            summary=(
                f"{_PREFIX}{rec.value} based on {len(cited)} blocking or review finding(s)"
                + _threshold_note(invoice, policy)
            ),
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
        session: ModelSession,
    ) -> Critique:
        omissions = [c for c in _cited_codes(findings) if c not in recommendation.cited_codes]
        expected = _rule(findings)
        consistent = (recommendation.recommendation is Recommendation.reject) == (
            expected is Recommendation.reject
        )
        agrees = not omissions and consistent
        high_value = _high_value(invoice, policy)
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

    def revise(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        recommendation: ApprovalRecommendation,
        critique: Critique,
        policy: PolicyContext,
        session: ModelSession,
    ) -> ApprovalRecommendation:
        rec = critique.revised_recommendation or recommendation.recommendation
        cited = [*recommendation.cited_codes]
        cited += [c for c in critique.omissions if c not in cited]
        return ApprovalRecommendation(
            recommendation=rec,
            reasons=[c.value for c in cited],
            cited_codes=cited,
            summary=f"{_PREFIX}revised to {rec.value} after critique"
            + _threshold_note(invoice, policy),
            mode=self.mode,
            provider=self.provider,
            model=self.model,
        )

    def assist_extraction(
        self, request: ExtractionAssistRequest, session: ModelSession
    ) -> ExtractionProposals:
        # Never called: ingestion runs the assist step in live mode only (offline never
        # triggers). Kept for the protocol, and proposes nothing.
        return ExtractionProposals(proposals=[])
