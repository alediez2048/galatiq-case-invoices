import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_processing import intake, ledger, payments, policy, seed
from invoice_processing.agents import approval, ingestion, payment, validation
from invoice_processing.agents.state import Deps, InvoiceState, emit
from invoice_processing.codes import (
    ExecutionMode,
    FindingCode,
    GateOutcome,
    RunStatus,
    Severity,
)
from invoice_processing.reasoning.offline import OfflineSimulator
from invoice_processing.schemas import ValidationFinding

EVAL_DATE = date(2026, 1, 20)
INV_1001 = Path("data/invoices/invoice_1001.txt")


@pytest.fixture
def deps(conn):
    seed.seed_inventory(conn)
    return Deps(conn=conn, provider=OfflineSimulator(), events=logging.getLogger("test.events"))


def _received(conn, source, raw) -> InvoiceState:
    ledger.record_source(conn, source)
    run_id = ledger.start_run(conn, ExecutionMode.offline, source.source_id, EVAL_DATE)
    return InvoiceState(
        run_id=run_id,
        mode=ExecutionMode.offline,
        evaluation_date=EVAL_DATE,
        source=source,
        raw=raw,
    )


@pytest.fixture
def received_state(deps) -> InvoiceState:
    source, raw = intake.read_source(INV_1001)
    return _received(deps.conn, source, raw)


@pytest.fixture
def received_state_bad_bytes(deps, tmp_path) -> InvoiceState:
    path = tmp_path / "bad.txt"
    path.write_bytes(b"\xff\xfe\x00bad")
    source, raw = intake.read_source(path)
    return _received(deps.conn, source, raw)


@pytest.fixture
def extracted_state(deps, received_state) -> InvoiceState:
    return {**received_state, **ingestion.run(received_state, deps)}


@pytest.fixture
def validated_state(deps, extracted_state) -> InvoiceState:
    return {**extracted_state, **validation.run(extracted_state, deps)}


@pytest.fixture
def approved_state(deps, validated_state) -> InvoiceState:
    return {**validated_state, **approval.run(validated_state, deps)}


def _run_status(deps, state) -> RunStatus:
    return ledger.get_run_status(deps.conn, state["run_id"])


def test_ingestion_extracts_inv_1001(deps, received_state):
    update = ingestion.run(received_state, deps)
    assert update["status"] == RunStatus.extracted
    assert update["version"] == 1
    assert [f.code for f in update["findings"]] == [FindingCode.currency_assumed_usd]
    assert update["invoice"].invoice_number == "INV-1001"
    assert "ingestion" in update["timings_ms"]
    assert _run_status(deps, received_state) == RunStatus.extracted
    events = ledger.list_audit_events(deps.conn, received_state["run_id"])
    extracted = [e for e in events if e["event"] == "extracted"]
    assert extracted[0]["stage"] == "ingestion"
    assert extracted[0]["payload"]["source_hash"] == received_state["source"].content_hash
    assert extracted[0]["payload"]["version"] == 1


def test_ingestion_decode_error_returns_failed(deps, received_state_bad_bytes):
    update = ingestion.run(received_state_bad_bytes, deps)
    assert update["status"] == RunStatus.failed
    assert update["error_code"] == "txt_decode_error"
    assert _run_status(deps, received_state_bad_bytes) == RunStatus.received


def test_validation_does_not_write_inventory(deps, extracted_state):
    query = "SELECT item, stock FROM inventory"
    before = dict(deps.conn.execute(query).fetchall())
    validation.run(extracted_state, deps)
    assert dict(deps.conn.execute(query).fetchall()) == before


def test_validation_keeps_normalization_findings_first_and_records(deps, extracted_state):
    update = validation.run(extracted_state, deps)
    assert update["status"] == RunStatus.validated
    assert update["findings"][0].code == FindingCode.currency_assumed_usd
    assert update["invoice"].computed.total == Decimal("5000.00")
    assert _run_status(deps, extracted_state) == RunStatus.validated
    rows = deps.conn.execute(
        "SELECT code FROM findings WHERE run_id = ?", (extracted_state["run_id"],)
    ).fetchall()
    assert [r["code"] for r in rows] == [f.code.value for f in update["findings"]]


def test_approval_one_critique_at_most_one_revision(deps, validated_state, monkeypatch):
    calls = {"recommend": 0, "critique": 0}
    recommend, critique = deps.provider.recommend, deps.provider.critique

    def counted_recommend(*a, **k):
        calls["recommend"] += 1
        return recommend(*a, **k)

    def counted_critique(*a, **k):
        calls["critique"] += 1
        return critique(*a, **k)

    monkeypatch.setattr(deps.provider, "recommend", counted_recommend, raising=False)
    monkeypatch.setattr(deps.provider, "critique", counted_critique, raising=False)
    approval.run(validated_state, deps)
    assert calls == {"recommend": 1, "critique": 1}


def test_approval_inv_1001_is_approved(deps, validated_state):
    update = approval.run(validated_state, deps)
    assert update["gate"].outcome == GateOutcome.approved
    assert update["gate"].rule_ids == ["R4_auto_approve"]
    assert update["status"] == RunStatus.approved
    assert update["decision"].final_decision == GateOutcome.approved
    assert update["decision"].policy_version == policy.POLICY_VERSION
    assert _run_status(deps, validated_state) == RunStatus.approved
    row = deps.conn.execute(
        "SELECT final_decision FROM decisions WHERE run_id = ?", (validated_state["run_id"],)
    ).fetchone()
    assert row["final_decision"] == "approved"
    events = ledger.list_audit_events(deps.conn, validated_state["run_id"])
    decision = [e for e in events if e["event"] == "decision"][0]
    assert decision["payload"]["policy_version"] == policy.POLICY_VERSION
    assert decision["payload"]["final_decision"] == "approved"
    assert decision["payload"]["rule_ids"] == ["R4_auto_approve"]
    assert {"recommendation", "critique"} <= {e["event"] for e in events}


def test_approval_blocker_sets_rejected(deps, validated_state):
    blocker = ValidationFinding(code=FindingCode.negative_tax, severity=Severity.blocker)
    state = {**validated_state, "findings": [*validated_state["findings"], blocker]}
    update = approval.run(state, deps)
    assert update["status"] == RunStatus.rejected
    assert _run_status(deps, state) == RunStatus.rejected


def test_pay_node_paid_mock_with_receipt(deps, approved_state):
    update = payment.pay_node(approved_state, deps)
    assert update["status"] == RunStatus.paid_mock
    assert update["receipt"].amount == Decimal("5000.00")
    assert update["receipt"].currency == "USD"
    assert "payment" in update["timings_ms"]
    assert _run_status(deps, approved_state) == RunStatus.paid_mock
    events = ledger.list_audit_events(deps.conn, approved_state["run_id"])
    paid = [e for e in events if e["event"] == "paid"][0]
    assert paid["payload"]["receipt_id"] == update["receipt"].receipt_id
    assert paid["payload"]["amount"] == "5000.00"
    assert paid["payload"]["currency"] == "USD"


def test_pay_node_refused_returns_failed(deps, validated_state):
    # No approved decision was persisted for this run.
    update = payment.pay_node(validated_state, deps)
    assert update["status"] == RunStatus.failed
    assert update["error_code"] == "payment_not_authorized:not_approved"
    assert deps.conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
    events = ledger.list_audit_events(deps.conn, validated_state["run_id"])
    assert "payment_refused" in {e["event"] for e in events}


def test_outcome_node_rejected_never_pays(deps, validated_state, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("pay must not be called")

    monkeypatch.setattr(payments, "pay", boom)
    blocker = ValidationFinding(code=FindingCode.negative_tax, severity=Severity.blocker)
    state = {**validated_state, "findings": [blocker], "status": RunStatus.rejected}
    update = payment.outcome_node(state, deps)
    assert "receipt" not in update
    assert "outcome" in update["timings_ms"]
    events = ledger.list_audit_events(deps.conn, state["run_id"])
    rejection = [e for e in events if e["event"] == "rejection_recorded"][0]
    assert rejection["payload"]["codes"] == ["negative_tax"]
    assert deps.conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_outcome_node_waiting_emits_waiting(deps, validated_state):
    state = {**validated_state, "status": RunStatus.needs_review}
    payment.outcome_node(state, deps)
    events = ledger.list_audit_events(deps.conn, state["run_id"])
    assert "waiting" in {e["event"] for e in events}


def test_emit_tolerates_missing_source(deps, received_state):
    run_id = received_state["run_id"]
    bare = InvoiceState(run_id=run_id, mode=ExecutionMode.offline)
    emit(deps, bare, "validation", "probe", codes=[FindingCode.zero_stock])
    row = deps.conn.execute(
        "SELECT payload_json FROM audit_events WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert '"source_hash": null' in row["payload_json"]
    assert '"codes": ["zero_stock"]' in row["payload_json"]


def test_only_payment_module_imports_pay():
    for path in Path("src/invoice_processing").rglob("*.py"):
        if path.name != "payments.py" and path != Path("src/invoice_processing/agents/payment.py"):
            text = path.read_text()
            assert "payments import pay" not in text
            assert "payments.pay(" not in text


def test_ingestion_records_normalization_findings_itself(deps, received_state):
    ingestion.run(received_state, deps)
    rows = deps.conn.execute(
        "SELECT code FROM findings WHERE run_id = ?", (received_state["run_id"],)
    ).fetchall()
    assert [r["code"] for r in rows] == ["currency_assumed_usd"]


def test_validation_failure_keeps_ingestion_findings(deps, extracted_state, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("invoice_processing.validation.check_required_fields", boom)
    with pytest.raises(RuntimeError):
        validation.run(extracted_state, deps)
    rows = deps.conn.execute(
        "SELECT code FROM findings WHERE run_id = ?", (extracted_state["run_id"],)
    ).fetchall()
    assert [r["code"] for r in rows] == ["currency_assumed_usd"]


def test_pay_node_paid_event_reports_created(deps, approved_state):
    payment.pay_node(approved_state, deps)
    first = [
        e
        for e in ledger.list_audit_events(deps.conn, approved_state["run_id"])
        if e["event"] == "paid"
    ][0]
    assert first["payload"]["created"] is True
    # A second run for the same (already paid) identity gets the existing receipt back.
    source = approved_state["source"]
    run2 = ledger.start_run(deps.conn, ExecutionMode.offline, source.source_id, EVAL_DATE)
    ledger.attach_run(deps.conn, run2, approved_state["invoice_id"], approved_state["version_id"])
    for s in (
        RunStatus.extracted,
        RunStatus.validated,
        RunStatus.approval_pending,
        RunStatus.approved,
    ):
        ledger.update_run_status(deps.conn, run2, s)
    update = payment.pay_node({**approved_state, "run_id": run2}, deps)
    assert update["status"] == RunStatus.paid_mock
    second = [e for e in ledger.list_audit_events(deps.conn, run2) if e["event"] == "paid"][0]
    assert second["payload"]["created"] is False
    assert deps.conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1
