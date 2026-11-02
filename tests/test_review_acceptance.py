"""P4-07 acceptance sequences for the human review workflow, through the public calls only.

Every scenario ends with at most one payment for its invoice. Thread-level concurrency tests
are deferred (see docs/tickets/P4-07). The module runs under the autouse `no_network` guard."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import grpc
import pytest

from invoice_processing import ledger, policy, review, service, storage
from invoice_processing.codes import (
    DEFAULT_SEVERITY,
    ExecutionMode,
    FindingCode,
    GateOutcome,
    HumanReviewAction,
    InvoiceStatus,
    Recommendation,
    ReviewRefusal,
    RunStatus,
    Severity,
)
from invoice_processing.reasoning.xai import XaiProvider
from invoice_processing.schemas import HumanReview, ValidationFinding
from invoice_processing.settings import LiveSettings
from tests.fakes.xai_client import FakeXaiClient, Parsed, Raise, factory
from tests.review_helpers import (
    EVAL,
    INVOICES,
    REVIEW,
    ROOT,
    change,
    correct,
    payment_count,
    process,
    seeded_db,
)

THRESHOLD = ROOT / "tests" / "fixtures" / "threshold"
AFTER_REC = REVIEW / "correction_after_recommendation.txt"
NOTE_LINE = "line:16"  # "Remittance note: due date extended to 2026-03-31 by agreement"
GATING = {Severity.blocker, Severity.review}
LIVE = ExecutionMode.live
SETTINGS = LiveSettings(api_key="sk-SENTINEL-123", model="grok-test")
UNAVAILABLE = Raise(grpc.StatusCode.UNAVAILABLE)


def refused(fn, *args, **kwargs) -> review.ReviewRefused:
    with pytest.raises(review.ReviewRefused) as e:
        fn(*args, **kwargs)
    return e.value


def audit(db: Path, run_id: str) -> list[tuple[str, dict]]:
    conn = storage.connect(db)
    try:
        rows = conn.execute(
            "SELECT event, payload_json FROM audit_events WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        ).fetchall()
        return [(r["event"], json.loads(r["payload_json"])) for r in rows]
    finally:
        conn.close()


def live_provider(*script) -> XaiProvider:
    return XaiProvider(SETTINGS, factory(FakeXaiClient(list(script))))


def rec() -> dict:
    return {"recommendation": "approve", "reasons": [], "cited_codes": [], "summary": "ok"}


def crit() -> dict:
    return {
        "agrees": True,
        "omissions": [],
        "high_value": False,
        "revised_recommendation": None,
        "summary": "critique agrees",
        "issues": [],
    }


# --- Threshold ----------------------------------------------------------------------------


def test_10000_00_pays_with_no_human_action(tmp_path):
    db = seeded_db(tmp_path)
    r = process(THRESHOLD / "valid_10000_00.json", db)
    assert r.status == "paid_mock" and r.receipt.amount == Decimal("10000.00")
    assert r.decision.human_review is None
    assert payment_count(db, r.invoice_id) <= 1


def test_10000_01_waits_then_approve_pays(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(THRESHOLD / "valid_10000_01.json", db)
    assert r1.status == "awaiting_human_approval" and payment_count(db, r1.invoice_id) == 0
    r2 = review.approve(r1.invoice_id, 1, "Ana", "Checked against PO", db_path=db)
    assert r2.status == "paid_mock" and r2.receipt.amount == Decimal("10000.01")
    assert payment_count(db, r1.invoice_id) <= 1


# --- Corrections --------------------------------------------------------------------------


def test_extraction_mistake_corrected_then_paid(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "extraction_mistake.txt", db)
    assert r1.status == "needs_review"
    r2 = correct(db, r1, change("stated.total", "3500.00", "line:13"))
    assert r2.status == "paid_mock" and r2.version == 2
    assert r2.receipt.amount == Decimal("3500.00")
    assert payment_count(db, r1.invoice_id) <= 1


def test_source_error_rejected_and_correction_refused(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "source_error.json", db)
    assert r1.status == "rejected"
    e = refused(correct, db, r1, change("stated.total", "5000.00", "$.total"))
    assert e.code is ReviewRefusal.correction_not_in_source
    assert e.current.status == "rejected" and e.current.current_version == 1
    assert payment_count(db, r1.invoice_id) <= 1


def test_correction_after_recommendation_invalidates_and_reruns(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(AFTER_REC, db)
    assert r1.status == "awaiting_human_approval" and r1.version == 1
    r2 = correct(db, r1, change("due_date", "2026-03-31", NOTE_LINE), reason="Due date extended")
    assert r2.status == "awaiting_human_approval" and r2.version == 2
    # the version 1 decision is listed as invalidated by the correction
    (invalidated,) = [p for e, p in audit(db, r2.run_id) if e == "approvals_invalidated"]
    assert invalidated["superseded_version"] == 1
    assert invalidated["decision_run_ids"] == [r1.run_id]
    # version 2 got its own recommendation and critique
    events = [e for e, _ in audit(db, r2.run_id)]
    assert events.count("recommendation") == 1 and events.count("critique") == 1
    assert r2.decision.initial_recommendation is not None
    assert r2.decision.critique_summary is not None
    e = refused(review.approve, r1.invoice_id, 1, "Ana", "Looks right", db_path=db)
    assert e.code is ReviewRefusal.stale_version and e.current.current_version == 2
    assert payment_count(db, r1.invoice_id) == 0
    r3 = review.approve(r1.invoice_id, 2, "Ana", "Looks right", db_path=db)
    assert r3.status == "paid_mock" and r3.version == 2
    r4 = review.approve(r1.invoice_id, 2, "Ana", "Looks right", db_path=db)
    assert r4.receipt.receipt_id == r3.receipt.receipt_id and r4.run_id == r3.run_id
    assert payment_count(db, r1.invoice_id) <= 1


# --- Restart between the wait and the approval ---------------------------------------------


def test_restart_between_wait_and_approve(tmp_path):
    db = tmp_path / "restart.db"
    env = {**os.environ, "INVOICE_NETWORK_GUARD": "1"}
    env.pop("XAI_API_KEY", None)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "main.py"),
            f"--invoice_path={THRESHOLD / 'valid_10000_01.json'}",
            "--db",
            str(db),
            f"--events={tmp_path / 'events.jsonl'}",
            "--evaluation-date=2026-01-31",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout)
    assert body["status"] == "awaiting_human_approval"
    # a fresh process: the approval opens its own connection to the same database
    r = review.approve(body["invoice_id"], body["version"], "Ana", "After restart", db_path=db)
    assert r.status == "paid_mock" and r.receipt.amount == Decimal("10000.01")
    assert payment_count(db, body["invoice_id"]) == 1


# --- Live model failure during re-review --------------------------------------------------


def test_live_failure_during_rereview_then_retry_pays(tmp_path):
    db = seeded_db(tmp_path)
    base = live_provider(Parsed({"proposals": []}), Parsed(rec()), Parsed(crit()))
    r1 = process(REVIEW / "extraction_mistake.txt", db, mode=LIVE, provider=base)
    assert r1.status == "needs_review" and r1.mode is LIVE
    r2 = correct(
        db,
        r1,
        change("stated.total", "3500.00", "line:13"),
        provider=live_provider(UNAVAILABLE, UNAVAILABLE),
    )
    assert r2.status is RunStatus.failed and r2.recoverable and r2.version == 2
    assert payment_count(db, r1.invoice_id) == 0
    r3 = service.retry_run(
        r2.run_id, None, db, EVAL, provider=live_provider(Parsed(rec()), Parsed(crit()))
    )
    assert r3.status == "paid_mock" and r3.version == 2
    assert payment_count(db, r1.invoice_id) <= 1


# --- Property: a human approval never overrides a blocker or review finding -----------------


GATING_CODES = sorted(c for c, s in DEFAULT_SEVERITY.items() if s in GATING)


def _clean_high_value(tmp_path):
    db = seeded_db(tmp_path)
    r = process(THRESHOLD / "valid_10000_01.json", db)
    conn = storage.connect(db)
    try:
        invoice = ledger.get_version(conn, r.invoice_id, 1).invoice
    finally:
        conn.close()
    approval = HumanReview(
        invoice_id=r.invoice_id,
        version=1,
        action=HumanReviewAction.approve,
        reviewer="Ana",
        reason="Checked",
        policy_version=policy.POLICY_VERSION,
        created_at=datetime.now(UTC),
    )
    return invoice, approval, r.invoice_id


def test_matching_approval_never_clears_a_gating_finding(tmp_path):
    assert GATING_CODES
    invoice, approval, invoice_id = _clean_high_value(tmp_path)
    clean = policy.evaluate(
        invoice, [], Recommendation.approve, approval, version=1, invoice_id=invoice_id
    )
    assert clean.outcome is GateOutcome.approved  # the approval itself does count
    for code in GATING_CODES:
        finding = ValidationFinding(code=code, severity=DEFAULT_SEVERITY[code])
        gate = policy.evaluate(
            invoice, [finding], Recommendation.approve, approval, version=1, invoice_id=invoice_id
        )
        assert gate.outcome is not GateOutcome.approved, code


def test_approve_refused_for_every_recorded_gating_code(tmp_path):
    db = seeded_db(tmp_path)
    for path in [*sorted(INVOICES.iterdir()), *sorted(REVIEW.glob("*.txt")), *THRESHOLD.iterdir()]:
        if path.suffix in {".txt", ".json", ".csv", ".xml", ".pdf"}:
            process(path, db)
    conn = storage.connect(db)
    try:
        held: dict[str, set[FindingCode]] = {}
        for row in conn.execute("SELECT invoice_id FROM invoices").fetchall():
            invoice = ledger.get_invoice(conn, row["invoice_id"])
            if invoice.current_version is None or invoice.status is InvoiceStatus.paid_mock:
                continue
            version = ledger.get_version(conn, invoice.invoice_id, invoice.current_version)
            run = ledger.latest_outcome_run(conn, version.version_id)
            found = {
                FindingCode(f["code"])
                for f in ledger.list_findings(conn, run.run_id)
                if f["severity"] in GATING
            }
            if found:
                held[invoice.invoice_id] = found
    finally:
        conn.close()
    queued = review.list_queue(db_path=db)
    queued_ids = {i.invoice_id for items in queued.groups.values() for i in items if i.reason_codes}
    assert queued_ids and queued_ids <= set(held)  # queued invoices with reasons are covered
    covered: set[FindingCode] = set()
    for invoice_id, found in held.items():
        version = review.allowed_actions(invoice_id, db_path=db).current_version
        e = refused(review.approve, invoice_id, version, "Ana", "Override", db_path=db)
        assert e.code is ReviewRefusal.action_not_allowed, (invoice_id, found)
        assert payment_count(db, invoice_id) <= 1
        covered |= found
    assert len(covered) >= 10  # the corpus records a wide spread of gating codes
