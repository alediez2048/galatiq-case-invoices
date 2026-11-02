import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from invoice_processing import ledger, storage

REPO_ROOT = Path(__file__).resolve().parents[1]
INVOICE = "data/invoices/invoice_1001.txt"


def run_cli(*args, db, events, extra_env=None):
    proc = subprocess.run(
        [
            sys.executable,
            "main.py",
            *args,
            f"--db={db}",
            f"--events={events}",
            "--evaluation-date=2026-01-20",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": "src", "INVOICE_NETWORK_GUARD": "1", **(extra_env or {})},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "network access blocked" not in proc.stderr, proc.stderr
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc, out


def _paths(tmp_path):
    return tmp_path / "i.db", tmp_path / "e.jsonl"


def _payment_count(db):
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    finally:
        c.close()


def test_e2e_inv_1001_paid(tmp_path):
    db, ev = _paths(tmp_path)
    proc, out = run_cli(f"--invoice_path={INVOICE}", db=db, events=ev)
    assert proc.returncode == 0, proc.stderr
    assert out["status"] == "paid_mock"
    assert out["mode"] == "offline"
    assert out["receipt"]["amount"] == "5000.00"
    assert out["receipt"]["currency"] == "USD"
    assert _payment_count(db) == 1


def test_e2e_rerun_duplicate(tmp_path):
    db, ev = _paths(tmp_path)
    run_cli(f"--invoice_path={INVOICE}", db=db, events=ev)
    proc, out = run_cli(f"--invoice_path={INVOICE}", db=db, events=ev)
    assert proc.returncode == 0, proc.stderr
    assert out["status"] == "duplicate"
    assert _payment_count(db) == 1


def test_e2e_restart_same_db(tmp_path):
    db, ev = _paths(tmp_path)
    run_cli(f"--invoice_path={INVOICE}", db=db, events=ev)
    copy = tmp_path / "renamed_copy.txt"
    shutil.copy(REPO_ROOT / INVOICE, copy)
    proc, out = run_cli(f"--invoice_path={copy}", db=db, events=ev)
    assert proc.returncode == 0, proc.stderr
    assert out["status"] == "duplicate"
    assert _payment_count(db) == 1


def test_e2e_corrupt_utf8_fails(tmp_path):
    db, ev = _paths(tmp_path)
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe\xff invalid \x80\x81")
    proc, out = run_cli(f"--invoice_path={bad}", db=db, events=ev)
    assert proc.returncode == 1
    assert out["status"] == "failed"
    assert _payment_count(db) == 0


def test_e2e_audit_trail(tmp_path):
    db, ev = _paths(tmp_path)
    proc, out = run_cli(f"--invoice_path={INVOICE}", db=db, events=ev)
    assert proc.returncode == 0, proc.stderr
    conn = storage.connect(db)
    try:
        events = ledger.list_audit_events(conn, out["run_id"])
    finally:
        conn.close()
    stages = []
    for e in events:
        if e["stage"] not in stages:
            stages.append(e["stage"])
    assert stages == ["intake", "ingestion", "validation", "approval", "payment", "service"]
    payloads = [e["payload"] for e in events]
    assert any(p.get("source_hash") == out["source_hash"] for p in payloads)
    assert any(p.get("mode") == "offline" for p in payloads)
    assert any(e["stage"] == "approval" and "policy_version" in e["payload"] for e in events)
    assert any(
        e["stage"] == "payment" and e["payload"].get("receipt_id") == out["receipt"]["receipt_id"]
        for e in events
    )


def test_e2e_never_touches_repo_db(tmp_path):
    repo_db = REPO_ROOT / "inventory.db"
    before = repo_db.stat().st_mtime if repo_db.exists() else None
    db, ev = _paths(tmp_path)
    proc, _ = run_cli(f"--invoice_path={INVOICE}", db=db, events=ev)
    assert proc.returncode == 0, proc.stderr
    after = repo_db.stat().st_mtime if repo_db.exists() else None
    assert before == after


def test_e2e_tracing_env_does_not_reach_network(tmp_path):
    db, ev = _paths(tmp_path)
    env = {
        "LANGSMITH_TRACING": "true",
        "LANGCHAIN_TRACING_V2": "true",
        "LANGSMITH_API_KEY": "dummy",
    }
    proc, out = run_cli(f"--invoice_path={INVOICE}", db=db, events=ev, extra_env=env)
    assert proc.returncode == 0, proc.stderr
    assert out["status"] == "paid_mock"
    assert "network access blocked" not in proc.stderr
