from decimal import Decimal

import pytest

from invoice_processing.codes import (
    DEFAULT_SEVERITY,
    FindingCode,
    GateOutcome,
    HumanReviewAction,
    Recommendation,
)
from invoice_processing.policy import (
    HIGH_VALUE_THRESHOLD_USD,
    POLICY_VERSION,
    context,
    evaluate,
)
from invoice_processing.schemas import HumanReview
from tests.helpers import codes, finding, invoice, line


def HR(version=1, action="approve", pv=POLICY_VERSION):
    return HumanReview(
        invoice_id="i",
        version=version,
        action=HumanReviewAction(action),
        reviewer="vp",
        reason="ok",
        policy_version=pv,
    )


CASES = [
    ("clean_10000.00", "10000.00", "USD", [], "approve", None, "approved", ["R4_auto_approve"]),
    (
        "clean_10000.01",
        "10000.01",
        "USD",
        [],
        "approve",
        None,
        "awaiting_human_approval",
        ["R3_high_value"],
    ),
    ("hv_with_review", "10000.01", "USD", [], "approve", HR(), "approved", ["R4_human_approved"]),
    (
        "hv_wrong_version",
        "10000.01",
        "USD",
        [],
        "approve",
        HR(version=2),
        "awaiting_human_approval",
        ["R3_high_value"],
    ),
    (
        "hv_wrong_policy",
        "10000.01",
        "USD",
        [],
        "approve",
        HR(pv="old"),
        "awaiting_human_approval",
        ["R3_high_value"],
    ),
    (
        "hv_declined",
        "10000.01",
        "USD",
        [],
        "approve",
        HR(action="decline"),
        "rejected",
        ["R3_human_declined"],
    ),
    (
        "blocker_approve",
        "5000.00",
        "USD",
        ["zero_stock"],
        "approve",
        None,
        "rejected",
        ["R1_blocker"],
    ),
    (
        "blocker_human",
        "5000.00",
        "USD",
        ["zero_stock"],
        "approve",
        HR(),
        "rejected",
        ["R1_blocker"],
    ),
    ("eur_clean", "4125.50", "EUR", [], "approve", None, "needs_review", ["R2_non_usd"]),
    ("eur_human", "4125.50", "EUR", [], "approve", HR(), "needs_review", ["R2_non_usd"]),
    (
        "model_reject_clean",
        "5000.00",
        "USD",
        [],
        "reject",
        None,
        "awaiting_human_approval",
        ["R3_model_disagreement"],
    ),
    ("model_reject_human", "5000.00", "USD", [], "reject", HR(), "approved", ["R4_human_approved"]),
    (
        "warning_only",
        "5000.00",
        "USD",
        ["due_date_past"],
        "approve",
        None,
        "approved",
        ["R4_auto_approve"],
    ),
]


def _inv(total, currency):
    return invoice(lines=[line("WidgetA", "1", total)], currency=currency, total=total)


@pytest.mark.parametrize(
    ("total", "currency", "fcodes", "rec", "hr", "outcome", "rule_ids"),
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_gate(total, currency, fcodes, rec, hr, outcome, rule_ids):
    findings = [finding(FindingCode(c)) for c in fcodes]
    result = evaluate(
        _inv(total, currency), findings, Recommendation(rec), hr, version=1, invoice_id="i"
    )
    assert result.outcome == GateOutcome(outcome)
    assert result.rule_ids == rule_ids


def test_gate_adds_disagreement_and_currency_findings():
    r = evaluate(_inv("5000.00", "EUR"), [], Recommendation.approve, None, version=1)
    assert codes(r.findings) == [FindingCode.non_usd_currency]
    assert r.findings[0].observed == "EUR"
    assert r.findings[0].severity == DEFAULT_SEVERITY[FindingCode.non_usd_currency]

    r = evaluate(_inv("5000.00", "USD"), [], Recommendation.reject, None, version=1)
    assert codes(r.findings) == [FindingCode.model_disagreement]
    assert r.findings[0].severity == DEFAULT_SEVERITY[FindingCode.model_disagreement]

    # disagreement is recorded even when a human approval lets it through
    r = evaluate(_inv("5000.00", "USD"), [], Recommendation.review, HR(), version=1, invoice_id="i")
    assert r.outcome == GateOutcome.approved
    assert codes(r.findings) == [FindingCode.model_disagreement]

    r = evaluate(_inv("5000.00", "USD"), [], Recommendation.approve, None, version=1)
    assert r.findings == []


def test_blocker_adds_no_findings_even_if_non_usd_or_disagreeing():
    r = evaluate(_inv("5000.00", "EUR"), [finding(FindingCode.zero_stock)], Recommendation.reject)
    assert r.outcome == GateOutcome.rejected
    assert r.findings == []


def test_both_review_rules_listed():
    r = evaluate(
        _inv("5000.00", "EUR"),
        [finding(FindingCode.unknown_item, DEFAULT_SEVERITY[FindingCode.non_usd_currency])],
        Recommendation.approve,
    )
    assert r.outcome == GateOutcome.needs_review
    assert r.rule_ids == ["R2_non_usd", "R2_review"]


def test_review_finding_alone():
    f = finding(FindingCode.non_usd_currency)
    r = evaluate(_inv("5000.00", "USD"), [f], Recommendation.approve)
    assert r.rule_ids == ["R2_review"]


def test_human_review_requires_version_argument():
    r = evaluate(_inv("10000.01", "USD"), [], Recommendation.approve, HR())
    assert r.outcome == GateOutcome.awaiting_human_approval


def test_missing_total_not_high_value():
    inv = invoice(lines=[line("WidgetA", "1", "1.00")], total=None)
    assert inv.stated.total is None
    r = evaluate(inv, [], Recommendation.approve)
    assert r.outcome == GateOutcome.approved
    assert "R3_high_value" not in r.rule_ids
    assert r.rule_ids == ["R4_auto_approve"]


def test_high_value_and_model_disagreement_combined():
    r = evaluate(_inv("10000.01", "USD"), [], Recommendation.reject, None, version=1)
    assert r.outcome == GateOutcome.awaiting_human_approval
    assert r.rule_ids == ["R3_high_value", "R3_model_disagreement"]


def test_context():
    ctx = context()
    assert ctx.policy_version == POLICY_VERSION == "2026-11-01.1"
    assert ctx.high_value_threshold == HIGH_VALUE_THRESHOLD_USD == Decimal("10000.00")


def test_human_review_for_other_invoice_does_not_count():
    inv = _inv("10000.01", "USD")
    r = evaluate(inv, [], Recommendation.approve, HR(), version=1, invoice_id="other")
    assert r.outcome == GateOutcome.awaiting_human_approval
    assert r.rule_ids == ["R3_high_value"]
    r = evaluate(inv, [], Recommendation.approve, HR(), version=1)  # no invoice_id given
    assert r.outcome == GateOutcome.awaiting_human_approval


def test_matching_decline_rejects():
    inv = _inv("10000.01", "USD")
    r = evaluate(inv, [], Recommendation.approve, HR(action="decline"), version=1, invoice_id="i")
    assert r.outcome == GateOutcome.rejected
    assert r.rule_ids == ["R3_human_declined"]
    assert codes(r.findings) == [FindingCode.human_declined]
    assert r.findings[0].severity == DEFAULT_SEVERITY[FindingCode.human_declined]
    # disagreement plus a decline: both findings are recorded
    r = evaluate(
        _inv("5000.00", "USD"),
        [],
        Recommendation.reject,
        HR(action="decline"),
        version=1,
        invoice_id="i",
    )
    assert r.outcome == GateOutcome.rejected
    assert codes(r.findings) == [FindingCode.model_disagreement, FindingCode.human_declined]


def test_decline_never_reached_past_blockers_or_review():
    blocker = [finding(FindingCode.zero_stock)]
    r = evaluate(
        _inv("10000.01", "USD"),
        blocker,
        Recommendation.approve,
        HR(action="decline"),
        version=1,
        invoice_id="i",
    )
    assert r.rule_ids == ["R1_blocker"] and r.findings == []
    r = evaluate(
        _inv("10000.01", "EUR"),
        [],
        Recommendation.approve,
        HR(action="decline"),
        version=1,
        invoice_id="i",
    )
    assert r.outcome == GateOutcome.needs_review


def test_mismatched_decline_does_not_reject():
    inv = _inv("10000.01", "USD")
    for hr, kw in [
        (HR(version=2, action="decline"), {"invoice_id": "i"}),
        (HR(action="decline", pv="old"), {"invoice_id": "i"}),
        (HR(action="decline"), {"invoice_id": "other"}),
    ]:
        r = evaluate(inv, [], Recommendation.approve, hr, version=1, **kw)
        assert r.outcome == GateOutcome.awaiting_human_approval
