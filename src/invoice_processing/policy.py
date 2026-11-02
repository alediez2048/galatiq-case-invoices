"""Deterministic eligibility gate (P1-04).

Model or simulator output never authorizes payment on its own. The gate decides from
findings, currency, stated total, and an optional matching human review.
"""

from decimal import Decimal

from invoice_processing.codes import (
    DEFAULT_SEVERITY,
    FindingCode,
    GateOutcome,
    HumanReviewAction,
    Recommendation,
    Severity,
)
from invoice_processing.reasoning.base import PolicyContext
from invoice_processing.schemas import (
    GateResult,
    HumanReview,
    NormalizedInvoice,
    ValidationFinding,
)

POLICY_VERSION = "2026-11-01.1"
HIGH_VALUE_THRESHOLD_USD = Decimal("10000.00")


def context() -> PolicyContext:
    return PolicyContext(
        policy_version=POLICY_VERSION, high_value_threshold=HIGH_VALUE_THRESHOLD_USD
    )


def _added(code: FindingCode, observed: str | None = None) -> ValidationFinding:
    return ValidationFinding(code=code, severity=DEFAULT_SEVERITY[code], observed=observed)


def evaluate(
    invoice: NormalizedInvoice,
    findings: list[ValidationFinding],
    recommendation: Recommendation,
    human_review: HumanReview | None = None,
    *,
    version: int | None = None,
    invoice_id: str | None = None,
) -> GateResult:
    """A human review counts only when its invoice, version and policy version all match.
    Under rule 3 a matching approve approves; a matching decline rejects (Decision 14)."""
    # Rule 1: blockers reject; a human review never clears them.
    if any(f.severity == Severity.blocker for f in findings):
        return GateResult(outcome=GateOutcome.rejected, rule_ids=["R1_blocker"], findings=[])

    added: list[ValidationFinding] = []

    # Rule 2: non-USD currency or any review finding needs review.
    rule_ids: list[str] = []
    if invoice.currency != "USD":
        rule_ids.append("R2_non_usd")
        added.append(_added(FindingCode.non_usd_currency, invoice.currency))
    if any(f.severity == Severity.review for f in findings):
        rule_ids.append("R2_review")
    if rule_ids:
        return GateResult(outcome=GateOutcome.needs_review, rule_ids=rule_ids, findings=added)

    # Rule 3: high value or model disagreement requires a matching human approval.
    matching = (
        human_review is not None
        and human_review.policy_version == POLICY_VERSION
        and version is not None
        and human_review.version == version
        and invoice_id is not None
        and human_review.invoice_id == invoice_id
    )
    action = human_review.action if matching else None
    total = invoice.stated.total
    high_value = total is not None and total > HIGH_VALUE_THRESHOLD_USD
    disagreement = recommendation != Recommendation.approve
    if disagreement:
        added.append(_added(FindingCode.model_disagreement))
    if high_value:
        rule_ids.append("R3_high_value")
    if disagreement:
        rule_ids.append("R3_model_disagreement")
    if rule_ids and action == HumanReviewAction.decline:
        added.append(_added(FindingCode.human_declined))
        return GateResult(
            outcome=GateOutcome.rejected, rule_ids=["R3_human_declined"], findings=added
        )
    if rule_ids and action != HumanReviewAction.approve:
        return GateResult(
            outcome=GateOutcome.awaiting_human_approval, rule_ids=rule_ids, findings=added
        )

    # Rule 4
    rule = "R4_human_approved" if rule_ids else "R4_auto_approve"
    return GateResult(outcome=GateOutcome.approved, rule_ids=[rule], findings=added)
