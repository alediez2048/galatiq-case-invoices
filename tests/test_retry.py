"""P3-08: recoverable live failures, explicit retry and labeled mode switches."""

import inspect
import json
import re
from datetime import date
from pathlib import Path

import grpc
import main
import pytest

from invoice_processing import ledger, reasoning, seed, service, storage
from invoice_processing.codes import ExecutionMode, FindingCode, RunStatus
from invoice_processing.reasoning import ProviderUnavailable
from invoice_processing.reasoning.xai import XaiProvider
from invoice_processing.service import RetryRefused, process_invoice, retry_run
from invoice_processing.settings import LiveSettings
from invoice_processing.storage import SchemaVersionError, connect
from tests.fakes.xai_client import FakeXaiClient, Parsed, Raise, factory

ROOT = Path(__file__).resolve().parent.parent
EVAL = date(2026, 1, 31)
LIVE, OFF = ExecutionMode.live, ExecutionMode.offline
SENTINEL = "sk-SENTINEL-123"
SETTINGS = LiveSettings(api_key=SENTINEL, model="grok-test")
INVOICES = ROOT / "data" / "invoices"
INV_1001 = INVOICES / "invoice_1001.txt"
INV_1004 = INVOICES / "invoice_1004.json"
INV_1004_REVISED = INVOICES / "invoice_1004_revised.json"
FAILED_MESSAGE = "Model request failed. Payment was not attempted."
UNAVAILABLE = Raise(grpc.StatusCode.UNAVAILABLE)


@pytest.fixture
def db(tmp_path) -> Path:
    path = tmp_path / "retry.db"
    c = connect(path)
    storage.init_schema(c)
    seed.seed_inventory(c)
    c.close()
    return path


def rec(decision="approve", cited=()):
    cited = [c.value if isinstance(c, FindingCode) else c for c in cited]
    return {"recommendation": decision, "reasons": cited, "cited_codes": cited, "summary": "ok"}


def crit():
    return {
        "agrees": True,
        "omissions": [],
        "high_value": False,
        "revised_recommendation": None,
        "summary": "critique agrees",
        "issues": [],
    }


def provider(*script) -> XaiProvider:
    return XaiProvider(SETTINGS, factory(FakeXaiClient(list(script))))


def working() -> XaiProvider:
    return provider(Parsed(rec()), Parsed(crit()))


def failing() -> XaiProvider:
    return provider(UNAVAILABLE, UNAVAILABLE)


def rows(db, sql, *args):
    c = connect(db)
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def run_row(db, run_id):
    (row,) = rows(db, "SELECT * FROM runs WHERE run_id = ?", run_id)
    return row


def n_payments(db) -> int:
    return rows(db, "SELECT COUNT(*) AS n FROM payments")[0]["n"]


# --- failure result and retry ----------------------------------------------------------


def test_live_failure_is_recoverable_and_retry_pays_once(db):
    failed = process_invoice(INV_1001, LIVE, db, EVAL, provider=failing())
    assert failed.status is RunStatus.failed
    assert failed.errors == ["model_unavailable"]
    assert failed.error_message == FAILED_MESSAGE
    assert failed.recoverable is True
    assert failed.next_actions == ["retry", "run offline as a separate simulation"]
    assert failed.receipt is None and n_payments(db) == 0

    retried = retry_run(failed.run_id, INV_1001, db, EVAL, provider=working())
    assert retried.run_id != failed.run_id
    assert retried.status is RunStatus.paid_mock and retried.mode is LIVE
    row = run_row(db, retried.run_id)
    assert row["retry_of"] == failed.run_id and row["mode"] == "live"
    assert row["mode_switch_of"] is None
    assert n_payments(db) == 1


def test_retry_of_a_retry_still_pays_once(db):
    first = process_invoice(INV_1001, LIVE, db, EVAL, provider=failing())
    second = retry_run(first.run_id, INV_1001, db, EVAL, provider=failing())
    assert second.status is RunStatus.failed and second.recoverable
    third = retry_run(second.run_id, INV_1001, db, EVAL, provider=working())
    assert third.status is RunStatus.paid_mock
    assert run_row(db, third.run_id)["retry_of"] == second.run_id
    assert n_payments(db) == 1


def test_retry_refused_for_paid_run(db):
    paid = process_invoice(INV_1001, OFF, db, EVAL)
    assert paid.status is RunStatus.paid_mock
    with pytest.raises(RetryRefused) as exc:
        retry_run(paid.run_id, INV_1001, db, EVAL)
    assert exc.value.reason == "not_failed"


def test_retry_refused_for_non_recoverable_failure(db, tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"Invoice Number: INV-9\nVendor: Caf\xe9 Ltd\n")
    failed = process_invoice(bad, OFF, db, EVAL)
    assert failed.status is RunStatus.failed and failed.errors == ["txt_decode_error"]
    assert failed.recoverable is False and failed.next_actions == []
    with pytest.raises(RetryRefused) as exc:
        retry_run(failed.run_id, bad, db, EVAL)
    assert exc.value.reason == "not_recoverable"


def test_retry_refused_for_a_different_file(db):
    failed = process_invoice(INV_1001, LIVE, db, EVAL, provider=failing())
    with pytest.raises(RetryRefused) as exc:
        retry_run(failed.run_id, INVOICES / "invoice_1002.txt", db, EVAL, provider=working())
    assert exc.value.reason == "source_mismatch"
    assert len(rows(db, "SELECT run_id FROM runs")) == 1  # a refusal creates no run


def test_retry_refused_for_unknown_run(db):
    with pytest.raises(RetryRefused) as exc:
        retry_run("run-nope", INV_1001, db, EVAL)
    assert exc.value.reason == "unknown_run"


def test_interrupted_run_is_retryable(db):
    c = connect(db)
    source_id, _ = ledger.record_source(c, _source(INV_1001))
    stale = ledger.start_run(c, OFF, source_id, EVAL)
    c.close()
    retried = retry_run(stale, INV_1001, db, EVAL)  # the startup sweep marks it interrupted
    assert run_row(db, stale)["error_code"] == "interrupted"
    assert retried.status is RunStatus.paid_mock and retried.mode is OFF
    assert n_payments(db) == 1


def _source(path):
    from invoice_processing import intake

    return intake.read_source(path)[0]


# --- mode switch -----------------------------------------------------------------------


def test_offline_run_after_failed_live_run_is_a_labeled_mode_switch(db):
    failed = process_invoice(INV_1001, LIVE, db, EVAL, provider=failing())
    offline = process_invoice(INV_1001, OFF, db, EVAL)
    assert offline.mode is OFF and offline.status is RunStatus.paid_mock
    row = run_row(db, offline.run_id)
    assert row["mode"] == "offline" and row["mode_switch_of"] == failed.run_id
    assert row["retry_of"] is None
    (decision,) = rows(db, "SELECT * FROM decisions")  # the failed live run has none
    assert decision["run_id"] == offline.run_id and decision["mode"] == "offline"
    assert json.loads(decision["payload_json"])["provider"] == "offline"
    assert n_payments(db) == 1


def test_live_run_after_offline_run_is_a_mode_switch_and_never_pays_twice(db):
    offline = process_invoice(INV_1001, OFF, db, EVAL)
    live = process_invoice(INV_1001, LIVE, db, EVAL, provider=working())
    assert run_row(db, live.run_id)["mode_switch_of"] == offline.run_id
    # the byte-level check is skipped; the payment still decides for the same identity
    assert live.status is RunStatus.duplicate
    assert live.receipt.receipt_id == offline.receipt.receipt_id
    assert rows(db, "SELECT run_id FROM decisions") == [{"run_id": offline.run_id}]
    assert n_payments(db) == 1


def test_same_mode_rerun_is_not_a_mode_switch(db):
    process_invoice(INV_1001, OFF, db, EVAL)
    again = process_invoice(INV_1001, OFF, db, EVAL)
    assert again.status is RunStatus.duplicate
    assert run_row(db, again.run_id)["mode_switch_of"] is None


def test_retry_after_offline_payment_reveals_receipt_and_keeps_payer(db):
    failed = process_invoice(INV_1001, LIVE, db, EVAL, provider=failing())
    offline = process_invoice(INV_1001, OFF, db, EVAL)
    retried = retry_run(failed.run_id, INV_1001, db, EVAL, provider=working())
    assert retried.receipt.receipt_id == offline.receipt.receipt_id
    assert run_row(db, retried.run_id)["mode_switch_of"] == offline.run_id
    # the paying run did not fail, so the payment stays attributed to it
    assert rows(db, "SELECT run_id FROM payments") == [{"run_id": offline.run_id}]
    assert n_payments(db) == 1


# --- identity check for retries --------------------------------------------------------


def test_retry_of_failed_revision_of_paid_invoice_needs_review(db):
    paid = process_invoice(INV_1004, OFF, db, EVAL)
    assert paid.status is RunStatus.paid_mock
    failed = process_invoice(INV_1004_REVISED, LIVE, db, EVAL, provider=failing())
    assert failed.status is RunStatus.failed and failed.errors == ["model_unavailable"]
    retried = retry_run(
        failed.run_id,
        INV_1004_REVISED,
        db,
        EVAL,
        provider=provider(
            Parsed(rec("review", cited=[FindingCode.revision_after_payment])), Parsed(crit())
        ),
    )
    assert retried.status is RunStatus.needs_review
    assert FindingCode.revision_after_payment in {f.code for f in retried.findings}
    assert rows(db, "SELECT amount FROM payments") == [{"amount": "1890.00"}]


# --- crash replay re-points the payment ------------------------------------------------


def test_crash_replay_repoints_payment_and_resubmission_shows_receipt(db, monkeypatch):
    real = ledger.update_run_status

    def fail_on_paid(conn, run_id, status):
        if status is RunStatus.paid_mock:
            raise RuntimeError("post-commit failure")
        return real(conn, run_id, status)

    with monkeypatch.context() as m:
        m.setattr(ledger, "update_run_status", fail_on_paid)
        crashed = process_invoice(INV_1001, OFF, db, EVAL)
    assert crashed.status is RunStatus.failed and n_payments(db) == 1
    replay = process_invoice(INV_1001, OFF, db, EVAL)
    assert replay.status is RunStatus.paid_mock
    assert rows(db, "SELECT run_id FROM payments") == [{"run_id": replay.run_id}]
    c = connect(db)
    repointed = [
        e
        for e in ledger.list_audit_events(c, replay.run_id)
        if e["event"] == "payment_run_repointed"
    ]
    c.close()
    assert len(repointed) == 1 and repointed[0]["stage"] == "payment"
    assert repointed[0]["payload"]["old_run_id"] == crashed.run_id
    assert repointed[0]["payload"]["new_run_id"] == replay.run_id

    again = process_invoice(INV_1001, OFF, db, EVAL)
    assert again.status is RunStatus.duplicate and again.prior_run_id == replay.run_id
    assert again.receipt.receipt_id == replay.receipt.receipt_id
    assert n_payments(db) == 1


# --- no silent offline fallback --------------------------------------------------------


def test_no_code_path_returns_offline_simulator_for_live_mode():
    for module in (reasoning, service):
        source = inspect.getsource(module)
        assert not re.search(r"except[^\n]*:\s*\n\s*.*OfflineSimulator", source)
    factory_src = inspect.getsource(reasoning.get_provider)
    live_branch = factory_src.split("if resolved is ExecutionMode.live:")[1].split("\n    from")[0]
    assert "OfflineSimulator" not in live_branch and "return xai.XaiProvider" in live_branch
    assert "OfflineSimulator" not in inspect.getsource(service)


def test_live_with_failing_settings_raises_and_creates_no_run(db, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env
    for k in ("XAI_API_KEY", "XAI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ProviderUnavailable):
        process_invoice(INV_1001, LIVE, db, EVAL)
    assert rows(db, "SELECT run_id FROM runs") == []


def test_retry_of_live_run_with_failing_settings_raises(db, monkeypatch, tmp_path):
    failed = process_invoice(INV_1001, LIVE, db, EVAL, provider=failing())
    monkeypatch.chdir(tmp_path)
    for k in ("XAI_API_KEY", "XAI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ProviderUnavailable):
        retry_run(failed.run_id, INV_1001, db, EVAL)
    assert len(rows(db, "SELECT run_id FROM runs")) == 1


# --- schema ----------------------------------------------------------------------------


def test_schema_v4_database_is_refused(tmp_path):
    assert storage.SCHEMA_VERSION == 5
    path = tmp_path / "v4.db"
    c = connect(path)
    c.execute("PRAGMA user_version = 4")
    with pytest.raises(SchemaVersionError):
        storage.init_schema(c)
    c.close()
    with pytest.raises(SchemaVersionError):
        process_invoice(INV_1001, OFF, path, EVAL)


# --- CLI -------------------------------------------------------------------------------


def _cli_args(tmp_path, *extra, invoice=INV_1001):
    return [
        f"--invoice_path={invoice}",
        f"--db={tmp_path / 'cli.db'}",
        f"--events={tmp_path / 'e.jsonl'}",
        "--evaluation-date=2026-01-31",
        *extra,
    ]


def test_cli_retry_uses_original_mode_and_pays_once(tmp_path, capsys, monkeypatch):
    from invoice_processing.reasoning import xai

    clients = iter(
        [FakeXaiClient([UNAVAILABLE, UNAVAILABLE]), FakeXaiClient([Parsed(rec()), Parsed(crit())])]
    )
    monkeypatch.setattr(xai, "real_client_factory", lambda settings: next(clients))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XAI_API_KEY", SENTINEL)
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    assert main.main(_cli_args(tmp_path, "--mode=live")) == 1
    failed = json.loads(capsys.readouterr().out)
    code = main.main(_cli_args(tmp_path, f"--retry={failed['run_id']}", "--mode=offline"))
    out, err = capsys.readouterr()
    assert code == 0
    assert f"Retrying run {failed['run_id']} (failed: model_unavailable)" in err
    assert "Mode: live model (grok-test)" in err  # --mode is ignored for a retry
    result = json.loads(out)
    assert result["status"] == "paid_mock" and result["mode"] == "live"
    assert "status=paid_mock" in err
    assert n_payments(tmp_path / "cli.db") == 1


def test_cli_retry_refusal_exits_2_with_reason(tmp_path, capsys):
    assert main.main(_cli_args(tmp_path)) == 0
    paid = json.loads(capsys.readouterr().out)
    code = main.main(_cli_args(tmp_path, f"--retry={paid['run_id']}"))
    out, err = capsys.readouterr()
    assert code == 2 and out == ""
    assert "not_failed" in err
    assert n_payments(tmp_path / "cli.db") == 1
