import os
import subprocess
import sys
from decimal import Decimal

import pytest

from invoice_processing.codes import C, ExecutionMode, Recommendation, Severity
from invoice_processing.reasoning import ProviderUnavailable, get_provider
from invoice_processing.reasoning.base import PolicyContext
from invoice_processing.reasoning.offline import OfflineSimulator
from invoice_processing.schemas import ApprovalRecommendation
from tests.helpers import finding, inv_1001, invoice, line

POLICY = PolicyContext(policy_version="test", high_value_threshold=Decimal("10000.00"))


@pytest.mark.parametrize(
    ("severities", "expected"),
    [
        ([], Recommendation.approve),
        ([Severity.warning], Recommendation.approve),
        ([Severity.review], Recommendation.review),
        ([Severity.review, Severity.blocker], Recommendation.reject),
    ],
)
def test_recommendation_rule(severities, expected):
    findings = [finding(C.zero_stock, s) for s in severities]
    rec = OfflineSimulator().recommend(inv_1001(), findings, POLICY)
    assert rec.recommendation is expected
    assert rec.mode is ExecutionMode.offline
    assert rec.provider == "offline" and rec.model == "simulated"


def test_cited_codes_dedupe_in_order():
    findings = [
        finding(C.zero_stock),
        finding(C.due_date_past),
        finding(C.non_usd_currency),
        finding(C.zero_stock),
    ]
    rec = OfflineSimulator().recommend(inv_1001(), findings, POLICY)
    assert rec.cited_codes == [C.zero_stock, C.non_usd_currency]
    assert rec.reasons == ["zero_stock", "non_usd_currency"]


def test_deterministic_and_labeled():
    s = OfflineSimulator()
    args = (inv_1001(), [], POLICY)
    assert s.recommend(*args) == s.recommend(*args)
    assert s.recommend(*args).summary.startswith("offline simulation: ")


def test_critique_flags_omitted_blocker_and_revises():
    findings = [finding(C.zero_stock)]
    bad = ApprovalRecommendation(
        recommendation=Recommendation.approve,
        reasons=[],
        cited_codes=[],
        summary="x",
        mode="offline",
        provider="offline",
        model="simulated",
    )
    c = OfflineSimulator().critique(inv_1001(), findings, bad, POLICY)
    assert not c.agrees and c.omissions == [C.zero_stock]
    assert c.revised_recommendation is Recommendation.reject
    assert c.summary.startswith("offline simulation: ")


def test_critique_agrees_with_own_recommendation():
    s = OfflineSimulator()
    findings = [finding(C.zero_stock)]
    rec = s.recommend(inv_1001(), findings, POLICY)
    c = s.critique(inv_1001(), findings, rec, POLICY)
    assert c.agrees and c.omissions == [] and c.revised_recommendation is None


def test_critique_flags_high_value():
    inv = invoice(lines=[line("WidgetA", "1", "10000.01")], total="10000.01")
    s = OfflineSimulator()
    rec = s.recommend(inv, [], POLICY)
    c = s.critique(inv, [], rec, POLICY)
    assert c.high_value is True and c.agrees is True
    assert (
        s.critique(inv_1001(), [], s.recommend(inv_1001(), [], POLICY), POLICY).high_value is False
    )


def test_critique_flags_inconsistent_recommendation():
    s = OfflineSimulator()
    findings = [finding(C.zero_stock)]
    rec = s.recommend(inv_1001(), findings, POLICY).model_copy(
        update={"recommendation": Recommendation.review}
    )
    c = s.critique(inv_1001(), findings, rec, POLICY)
    assert not c.agrees and c.omissions == []
    assert c.revised_recommendation is Recommendation.reject


def test_assist_extraction_returns_draft_unchanged():
    sentinel = object()
    assert OfflineSimulator().assist_extraction("text", sentinel) is sentinel  # type: ignore[arg-type]


def test_get_provider_offline():
    assert isinstance(get_provider("offline"), OfflineSimulator)
    assert isinstance(get_provider(ExecutionMode.offline), OfflineSimulator)


def test_get_provider_live_fails_without_fallback():
    with pytest.raises(ProviderUnavailable):
        get_provider("live")


def test_get_provider_unknown_value():
    with pytest.raises(ValueError):
        get_provider("bogus")


def test_offline_provider_imports_no_model_sdk():
    code = (
        "import sys, invoice_processing.reasoning as r; r.get_provider('offline'); "
        "print(any(m.split('.')[0] in {'xai_sdk','openai','anthropic','httpx'} "
        "for m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
        check=True,
    ).stdout.strip()
    assert out == "False"
