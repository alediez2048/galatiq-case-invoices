import io
import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal

from invoice_processing.codes import ExecutionMode, RunStatus
from invoice_processing.observability import (
    configure_events,
    format_summary,
    log_event,
    stage_timer,
    write_result,
)
from invoice_processing.schemas import MockReceipt, ProcessingResult


def make_result(with_receipt: bool = True) -> ProcessingResult:
    receipt = (
        MockReceipt(
            receipt_id="rcpt-1",
            amount=Decimal("5000.00"),
            currency="USD",
            paid_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        if with_receipt
        else None
    )
    return ProcessingResult(
        run_id="r1",
        invoice_id="inv-1",
        status=RunStatus.paid_mock if with_receipt else RunStatus.rejected,
        mode=ExecutionMode.offline,
        receipt=receipt,
    )


def test_every_event_line_is_json_with_run_id_and_stage(tmp_path):
    lg = configure_events(tmp_path / "e.jsonl")
    log_event(lg, run_id="r1", stage="ingestion", event="extracted", status="extracted", codes=[])
    log_event(lg, run_id="r1", stage="payment", event="paid", duration_ms=3)
    lines = (tmp_path / "e.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert all({"run_id", "stage", "ts"} <= json.loads(line).keys() for line in lines)


def test_redaction(tmp_path):
    lg = configure_events(tmp_path / "e.jsonl")
    log_event(lg, run_id="r", stage="s", event="e", api_key="sk-secret", nested={"auth_token": "t"})
    text = (tmp_path / "e.jsonl").read_text()
    assert "sk-secret" not in text and "auth_token" not in text
    assert json.loads(text)["nested"] == {}


def test_hyphenated_header_dropped(tmp_path):
    lg = configure_events(tmp_path / "e.jsonl")
    log_event(lg, run_id="r", stage="s", event="e", headers={"x-api-key": "k"})
    line = (tmp_path / "e.jsonl").read_text()
    assert "x-api-key" not in line and json.loads(line)["headers"] == {}


def test_business_keys_not_redacted(tmp_path):
    lg = configure_events(tmp_path / "e.jsonl")
    log_event(lg, run_id="r", stage="s", event="e", vendor_key="widgets inc.")
    assert json.loads((tmp_path / "e.jsonl").read_text())["vendor_key"] == "widgets inc."


def test_configure_events_replaces_handler(tmp_path):
    configure_events(tmp_path / "a.jsonl")
    lg = configure_events(tmp_path / "sub" / "b.jsonl")
    assert len(lg.handlers) == 1 and lg.propagate is False
    log_event(lg, run_id=None, stage="s", event="e")
    assert not (tmp_path / "a.jsonl").exists() or (tmp_path / "a.jsonl").read_text() == ""
    assert json.loads((tmp_path / "sub" / "b.jsonl").read_text())["run_id"] is None


def test_configure_events_defaults_to_stderr(capsys):
    lg = configure_events(None)
    log_event(lg, run_id="r", stage="s", event="e")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err.strip())["event"] == "e"


def test_write_result_money_as_strings(capsys):
    write_result(make_result())
    out = capsys.readouterr().out
    assert out.endswith("\n")
    assert json.loads(out)["receipt"]["amount"] == "5000.00"


def test_write_result_to_path_and_stream(tmp_path):
    path = tmp_path / "out" / "result.json"
    write_result(make_result(), path)
    assert json.loads(path.read_text())["run_id"] == "r1"
    buf = io.StringIO()
    write_result(make_result(), buf)
    assert json.loads(buf.getvalue())["status"] == "paid_mock"


def test_stage_timer_sets_duration():
    with stage_timer() as t:
        pass
    assert isinstance(t["duration_ms"], int) and t["duration_ms"] >= 0


def test_format_summary():
    s = format_summary(make_result())
    assert "paid_mock" in s and "inv-1" in s and "USD 5,000.00" in s
    assert "r1" in format_summary(make_result(with_receipt=False))


def test_output_paths_are_gitignored():
    out = subprocess.run(
        ["git", "check-ignore", "output/events.jsonl", "output/result.json"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
