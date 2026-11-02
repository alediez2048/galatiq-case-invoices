"""Version-bound human approve/decline (P4-04, Decisions 13, 14, 20): the review run
revalidates, never calls a model, and pays at most once per invoice."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from invoice_processing import ledger, payments, review, service, storage
from invoice_processing.codes import (
    ExecutionMode,
    FindingCode,
    GateOutcome,
    HumanReviewAction,
    Recommendation,
    ReviewRefusal,
    RunStatus,
)
from invoice_processing.policy import POLICY_VERSION
from invoice_processing.reasoning.offline import OfflineSimulator
from invoice_processing.reasoning.xai import XaiProvider
from invoice_processing.schemas import ApprovalDecision, HumanReview
from invoice_processing.settings import LiveSettings
from tests.fakes.xai_client import FakeXaiClient, Parsed, factory
from tests.review_helpers import (
    EVAL,
    INVOICES,
    REVIEW,
    change,
    correct,
    count,
    payment_count,
    process,
    seeded_db,
)

THRESHOLD = Path(__file__).resolve().parent / "fixtures" / "threshold"
AFTER_REC = REVIEW / "correction_after_recommendation.txt"
NOTE_LINE = "line:16"  # "Remittance note: due date extended to 2026-03-31 by agreement"


def refused(fn, *args, **kwargs) -> review.ReviewRefused:
    with pytest.raises(review.ReviewRefused) as e:
        fn(*args, **kwargs)
    return e.value


def codes(result) -> list[str]:
    return [f.code.value for f in result.findings]


def test_10000_00_auto_pays(tmp_path):
    r = process(THRESHOLD / "valid_10000_00.json", seeded_db(tmp_path))
    assert r.status == "paid_mock" and r.receipt.amount == Decimal("10000.00")


def test_10000_01_waits_then_approve_pays_once(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(THRESHOLD / "valid_10000_01.json", db)
    assert r1.status == "awaiting_human_approval" and r1.receipt is None
    assert payment_count(db, r1.invoice_id) == 0
    r2 = review.approve(r1.invoice_id, 1, "Ana", "Checked against PO", db_path=db)
    assert r2.status == "paid_mock" and r2.receipt.amount == Decimal("10000.01")
    assert r2.decision.reasons == ["R4_human_approved"]
    assert r2.decision.human_review.reviewer == "Ana"
    assert r2.decision.human_review.action is HumanReviewAction.approve
    assert r2.decision.final_decision is GateOutcome.approved
    assert r2.decision.initial_recommendation is r1.decision.initial_recommendation
    assert r2.decision.critique_summary == r1.decision.critique_summary
    assert r2.decision.model_calls_used == 0
    assert r2.version == 1 and r2.run_id != r1.run_id
    run = review_run(db, r2.run_id)
    assert (run["trigger"], run["review_of"]) == ("human_review", r1.run_id)
    events = audit_events(db, r2.run_id)
    applied = [e for e in events if e["event"] == "human_review_applied"]
    assert len(applied) == 1 and applied[0]["actor"] == "Ana"
    assert "decision" in [e["event"] for e in events]
    r3 = review.approve(r1.invoice_id, 1, "Ana", "again", db_path=db)
    assert r3.receipt.receipt_id == r2.receipt.receipt_id
    assert r3.run_id == r2.run_id and r3.status == "paid_mock"
    assert payment_count(db, r1.invoice_id) == 1
    # the repeated approve wrote nothing (Decision 20)
    assert count(db, "SELECT COUNT(*) FROM human_reviews") == 1
    assert count(db, "SELECT COUNT(*) FROM runs") == 2


def review_run(db, run_id) -> dict:
    conn = storage.connect(db)
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def audit_events(db, run_id) -> list[dict]:
    conn = storage.connect(db)
    try:
        rows = conn.execute(
            "SELECT event, actor FROM audit_events WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def test_blank_reason_raises_before_any_database_access(tmp_path):
    missing = tmp_path / "nowhere" / "missing.db"
    with pytest.raises(ValidationError):
        review.approve("inv-x", 1, "Ana", "   ", db_path=missing)
    with pytest.raises(ValidationError):
        review.decline("inv-x", 1, "", "Wrong PO", db_path=missing)
    assert not missing.parent.exists()


def test_unknown_invoice_refused(tmp_path):
    db = seeded_db(tmp_path)
    e = refused(review.approve, "inv-missing", 1, "Ana", "ok", db_path=db)
    assert e.code is ReviewRefusal.unknown_invoice and e.current is None


def test_decline_rejects_and_later_approve_refused(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(THRESHOLD / "valid_10000_01.json", db)
    r2 = review.decline(r1.invoice_id, 1, "Ana", "Vendor not on contract", db_path=db)
    assert r2.status == "rejected"
    assert "human_declined" in codes(r2)
    assert r2.decision.reasons == ["R3_human_declined"]
    assert r2.decision.final_decision is GateOutcome.rejected
    assert r2.decision.human_review.reason == "Vendor not on contract"
    assert r2.decision.human_review.action is HumanReviewAction.decline
    e = refused(review.approve, r1.invoice_id, 1, "Ana", "changed my mind", db_path=db)
    assert e.code is ReviewRefusal.action_not_allowed
    assert e.current.status == "rejected"
    assert payment_count(db, r1.invoice_id) == 0


def test_approve_stale_after_correction(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(AFTER_REC, db)
    assert r1.status == "awaiting_human_approval" and r1.version == 1
    r2 = correct(db, r1, change("due_date", "2026-03-31", NOTE_LINE), reason="Due date extended")
    assert r2.status == "awaiting_human_approval" and r2.version == 2
    assert r2.decision.critique_summary is not None
    e = refused(review.approve, r1.invoice_id, 1, "Ana", "Looks right", db_path=db)
    assert e.code is ReviewRefusal.stale_version and e.current.current_version == 2
    assert payment_count(db, r1.invoice_id) == 0
    r3 = review.approve(r1.invoice_id, 2, "Ana", "Looks right", db_path=db)
    assert r3.status == "paid_mock" and r3.receipt.amount == Decimal("12000.00")
    assert r3.version == 2


def _approved_decision() -> ApprovalDecision:
    return ApprovalDecision(
        initial_recommendation=Recommendation.approve,
        final_decision=GateOutcome.approved,
        reasons=["R4_human_approved"],
        policy_version=POLICY_VERSION,
        mode=ExecutionMode.offline,
    )


def test_pay_refuses_superseded_version_even_with_forged_approval(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(AFTER_REC, db)
    correct(db, r1, change("due_date", "2026-03-31", NOTE_LINE), reason="Due date extended")
    conn = storage.connect(db)
    try:
        v1 = ledger.get_version(conn, r1.invoice_id, 1)
        assert v1.version_status == "superseded"
        # a fresh run on v1 (the waiting run already has its decision row)
        run = ledger.start_run(conn, ExecutionMode.offline, v1.source_id, r1.evaluation_date)
        ledger.attach_run(conn, run, r1.invoice_id, v1.version_id)
        ledger.record_decision(conn, run, v1.version_id, _approved_decision())
        forged = HumanReview(
            invoice_id=r1.invoice_id,
            version=1,
            action=HumanReviewAction.approve,
            reviewer="Mallory",
            reason="forged",
            policy_version=POLICY_VERSION,
        )
        ledger.record_human_review(conn, forged, run)
        with pytest.raises(payments.PaymentNotAuthorized) as e:
            payments.pay(conn, r1.invoice_id, v1.version_id, run)
        assert e.value.reason == "stale_version"
    finally:
        conn.close()
    assert payment_count(db, r1.invoice_id) == 0


def test_pay_without_human_review_over_threshold_raises(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(THRESHOLD / "valid_10000_01.json", db)
    conn = storage.connect(db)
    try:
        v1 = ledger.get_version(conn, r1.invoice_id, 1)
        run = ledger.start_run(conn, ExecutionMode.offline, v1.source_id, r1.evaluation_date)
        ledger.attach_run(conn, run, r1.invoice_id, v1.version_id)
        ledger.record_decision(conn, run, v1.version_id, _approved_decision())
        with pytest.raises(payments.PaymentNotAuthorized) as e:
            payments.pay(conn, r1.invoice_id, v1.version_id, run)
        assert e.value.reason == "human_approval_required"
    finally:
        conn.close()
    assert payment_count(db, r1.invoice_id) == 0


class AlwaysReject(OfflineSimulator):
    """Recommends reject on a clean invoice; its critique agrees, so no revision runs."""

    def recommend(self, invoice, findings, policy, session):
        rec = super().recommend(invoice, findings, policy, session)
        return rec.model_copy(update={"recommendation": Recommendation.reject})

    def critique(self, invoice, findings, recommendation, policy, session):
        crit = super().critique(invoice, findings, recommendation, policy, session)
        return crit.model_copy(update={"agrees": True, "revised_recommendation": None})


def test_model_disagreement_wait_uses_same_actions(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(INVOICES / "invoice_1001.txt", db, provider=AlwaysReject())
    assert r1.status == "awaiting_human_approval"
    assert "model_disagreement" in codes(r1)
    actions = review.allowed_actions(r1.invoice_id, db_path=db)
    assert {"approve", "decline"} <= set(actions.allowed)
    r2 = review.approve(r1.invoice_id, 1, "Ana", "Model was wrong", db_path=db)
    assert r2.status == "paid_mock" and r2.receipt.amount == Decimal("5000.00")
    assert r2.decision.reasons == ["R4_human_approved"]
    assert "model_disagreement" in codes(r2)


def test_crossed_and_late_actions(tmp_path):
    db = seeded_db(tmp_path)
    r_review = process(INVOICES / "invoice_1014.xml", db)
    assert r_review.status == "needs_review"
    e = refused(review.approve, r_review.invoice_id, 1, "Ana", "ok", db_path=db)
    assert e.code is ReviewRefusal.action_not_allowed
    e = refused(review.decline, r_review.invoice_id, 1, "Ana", "no", db_path=db)
    assert e.code is ReviewRefusal.action_not_allowed

    r1 = process(THRESHOLD / "valid_10000_01.json", db)
    paid = review.approve(r1.invoice_id, 1, "Ana", "ok", db_path=db)
    assert paid.status == "paid_mock" and payment_count(db, r1.invoice_id) == 1
    e = refused(review.decline, r1.invoice_id, 1, "Bo", "too late", db_path=db)
    assert e.code is ReviewRefusal.already_paid
    e = refused(review.approve, r1.invoice_id, 2, "Bo", "other version", db_path=db)
    assert e.code is ReviewRefusal.stale_version
    again = review.approve(r1.invoice_id, 1, "Bo", "double click", db_path=db)
    third = review.approve(r1.invoice_id, 1, "Bo", "double click", db_path=db)
    assert again.receipt.receipt_id == third.receipt.receipt_id == paid.receipt.receipt_id
    assert payment_count(db, r1.invoice_id) == 1
    # INV-1014 never paid; the 10000.01 invoice paid exactly once
    assert count(db, "SELECT COUNT(*) FROM payments") == 1


def _live_rec(summary: str) -> dict:
    return {"recommendation": "approve", "reasons": [], "cited_codes": [], "summary": summary}


def _live_crit() -> dict:
    return {
        "agrees": True,
        "omissions": [],
        "high_value": True,
        "revised_recommendation": None,
        "summary": "critique agrees",
        "issues": [],
    }


def test_approval_never_calls_a_model(tmp_path, monkeypatch):
    db = seeded_db(tmp_path)
    client = FakeXaiClient(
        [
            Parsed(_live_rec("Total 10,000.01 is above the 10,000.00 threshold")),
            Parsed(_live_crit()),
        ]
    )
    provider = XaiProvider(
        LiveSettings(api_key="sk-SENTINEL-123", model="grok-test"), factory(client)
    )
    r1 = process(THRESHOLD / "valid_10000_01.json", db, ExecutionMode.live, provider)
    assert r1.status == "awaiting_human_approval" and r1.mode == "live"
    seen = len(client.requests)
    later = FakeXaiClient([])
    monkeypatch.setattr("invoice_processing.reasoning.xai.real_client_factory", lambda s: later)
    r2 = review.approve(r1.invoice_id, 1, "Ana", "Checked", db_path=db)  # no XAI_* env set
    assert r2.status == "paid_mock" and r2.mode == "live"
    assert r2.decision.provider == r1.decision.provider and r2.decision.model == "grok-test"
    assert r2.decision.model_calls_used == 0
    assert len(client.requests) == seen and later.requests == []


def test_approval_revalidates(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(THRESHOLD / "valid_10000_01.json", db)
    assert r1.status == "awaiting_human_approval"
    conn = storage.connect(db)
    try:
        with conn:
            conn.execute("UPDATE inventory SET stock = 0 WHERE item = 'WidgetA'")
    finally:
        conn.close()
    r2 = review.approve(r1.invoice_id, 1, "Ana", "Checked", db_path=db)
    assert r2.status == "rejected"
    assert {"zero_stock", "quantity_exceeds_stock"} & set(codes(r2))
    assert r2.decision.reasons == ["R1_blocker"]
    assert payment_count(db, r1.invoice_id) == 0


def test_load_result_rebuilds_a_finished_run(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(THRESHOLD / "valid_10000_01.json", db)
    r2 = review.approve(r1.invoice_id, 1, "Ana", "ok", db_path=db)
    loaded = review.load_result(r2.run_id, db_path=db)
    assert loaded.status is RunStatus.paid_mock and loaded.receipt == r2.receipt
    assert loaded.decision == r2.decision and loaded.version == 1
    assert loaded.invoice_id == r1.invoice_id and loaded.mode is ExecutionMode.offline
    assert [f.code for f in loaded.findings] == [f.code for f in r2.findings]
    waiting = review.load_result(r1.run_id, db_path=db)
    assert waiting.status is RunStatus.awaiting_human_approval and waiting.receipt is None
    assert FindingCode.model_disagreement not in [f.code for f in loaded.findings]


def test_no_model_provider_refuses_every_call():
    from invoice_processing.reasoning.base import NoModelProvider

    p = NoModelProvider(ExecutionMode.live)
    assert (p.mode, p.provider, p.model, p.prompt_version) == (
        ExecutionMode.live,
        "none",
        "none",
        None,
    )
    calls = [
        (p.recommend, 4),
        (p.critique, 5),
        (p.revise, 6),
        (p.assist_extraction, 2),
    ]
    for method, arity in calls:
        with pytest.raises(AssertionError, match="human-review runs make no model calls"):
            method(*[None] * arity)


def _interrupted_approve(db, invoice_id, monkeypatch, action="approve") -> str:
    """Commit the approve/decline transaction, then stop before the graph runs (a crash):
    the next retry's startup sweep marks the run `interrupted`."""
    with monkeypatch.context() as m:
        m.setattr(service, "run_existing_version", lambda run_id, **kw: run_id)
        return getattr(review, action)(invoice_id, 1, "Ana", "Checked", db_path=db)


class NoCalls(OfflineSimulator):
    def recommend(self, *a, **k):
        raise AssertionError("retry of a human-review run called the model")


def test_interrupted_approve_is_retried_without_a_model_or_file(tmp_path, monkeypatch):
    db = seeded_db(tmp_path)
    r1 = process(THRESHOLD / "valid_10000_01.json", db)
    run_id = _interrupted_approve(db, r1.invoice_id, monkeypatch)
    checked = service.check_retry(run_id, None, db)  # checked without a file too
    assert checked.trigger == "human_review" and checked.error_code == "interrupted"
    r = service.retry_run(run_id, None, db, EVAL, provider=NoCalls())
    assert r.status == "paid_mock" and r.receipt.amount == Decimal("10000.01")
    assert r.decision.reasons == ["R4_human_approved"] and r.decision.model_calls_used == 0
    row = review_run(db, r.run_id)
    assert (row["trigger"], row["review_of"], row["retry_of"]) == (
        "human_review",
        r1.run_id,
        run_id,
    )
    assert review_run(db, run_id)["error_code"] == "interrupted"
    assert payment_count(db, r1.invoice_id) == 1
    assert count(db, "SELECT COUNT(*) FROM human_reviews") == 1


def test_interrupted_decline_retry_rejects(tmp_path, monkeypatch):
    db = seeded_db(tmp_path)
    r1 = process(THRESHOLD / "valid_10000_01.json", db)
    run_id = _interrupted_approve(db, r1.invoice_id, monkeypatch, action="decline")
    r = service.retry_run(run_id, None, db, EVAL)
    assert r.status == "rejected" and r.decision.reasons == ["R3_human_declined"]
    assert payment_count(db, r1.invoice_id) == 0


def test_interrupted_live_approve_retries_with_no_credentials(tmp_path, monkeypatch):
    db = seeded_db(tmp_path)
    client = FakeXaiClient(
        [
            Parsed(_live_rec("Total 10,000.01 is above the 10,000.00 threshold")),
            Parsed(_live_crit()),
        ]
    )
    settings = LiveSettings(api_key="sk-SENTINEL-123", model="grok-test")
    provider = XaiProvider(settings, factory(client))
    r1 = process(THRESHOLD / "valid_10000_01.json", db, ExecutionMode.live, provider)
    assert r1.status == "awaiting_human_approval"
    seen = len(client.requests)
    later = FakeXaiClient([])
    monkeypatch.setattr("invoice_processing.reasoning.xai.real_client_factory", lambda s: later)
    run_id = _interrupted_approve(db, r1.invoice_id, monkeypatch)
    r = service.retry_run(run_id, None, db, EVAL)  # no XAI_* env, no provider given
    assert r.status == "paid_mock" and r.mode == "live"
    assert len(client.requests) == seen and later.requests == []
    assert payment_count(db, r1.invoice_id) == 1


def test_interrupted_approve_with_a_file_still_skips_ingestion(tmp_path, monkeypatch):
    db = seeded_db(tmp_path)
    r1 = process(THRESHOLD / "valid_10000_01.json", db)
    run_id = _interrupted_approve(db, r1.invoice_id, monkeypatch)
    r = service.retry_run(run_id, THRESHOLD / "valid_10000_01.json", db, EVAL, provider=NoCalls())
    assert r.status == "paid_mock"
    assert review_run(db, r.run_id)["trigger"] == "human_review"


def test_on_run_started_fires_with_the_result_run_id(tmp_path):
    db = seeded_db(tmp_path)
    started: list[str] = []
    r1 = process(AFTER_REC, db)
    r2 = review.submit_correction(_due_date_request(r1), db_path=db, on_run_started=started.append)
    assert started == [r2.run_id]
    r3 = review.approve(r1.invoice_id, 2, "Ana", "ok", db_path=db, on_run_started=started.append)
    assert started == [r2.run_id, r3.run_id] and r3.status == "paid_mock"
    # a repeated approve of the paid version starts no run, so the hook does not fire
    review.approve(r1.invoice_id, 2, "Ana", "again", db_path=db, on_run_started=started.append)
    assert len(started) == 2
    r4 = process(THRESHOLD / "valid_10000_01.json", db)
    r5 = review.decline(r4.invoice_id, 1, "Ana", "no", db_path=db, on_run_started=started.append)
    assert started[-1] == r5.run_id and len(started) == 3


def _due_date_request(result):
    from invoice_processing.schemas import CorrectionRequest

    return CorrectionRequest(
        invoice_id=result.invoice_id,
        expected_version=result.version,
        changes=[change("due_date", "2026-03-31", NOTE_LINE)],
        reason="Due date extended",
        reviewer="Ana",
    )
