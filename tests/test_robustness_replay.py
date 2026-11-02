"""P6-01 campaign 4: payment replay through repeated real CLI subprocess runs."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "invoices"


def cli(tmp_path, invoice, *extra, db="r.db"):
    env = {**os.environ, "INVOICE_NETWORK_GUARD": "1"}
    env.pop("XAI_API_KEY", None)
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "main.py"),
            f"--invoice_path={invoice}",
            f"--db={tmp_path / db}",
            f"--events={tmp_path / 'e.jsonl'}",
            "--evaluation-date=2026-01-31",
            *extra,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
    )


def rows(tmp_path, sql, db="r.db"):
    c = sqlite3.connect(tmp_path / db)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


def test_repeated_cli_runs_pay_exactly_once(tmp_path):
    invoice = CORPUS / "invoice_1001.txt"
    results = [cli(tmp_path, invoice) for _ in range(4)]
    assert [r.returncode for r in results] == [0, 0, 0, 0]
    bodies = [json.loads(r.stdout) for r in results]
    assert [b["status"] for b in bodies] == ["paid_mock", "duplicate", "duplicate", "duplicate"]
    receipt_ids = {b["receipt"]["receipt_id"] for b in bodies}
    assert len(receipt_ids) == 1
    assert all(b["prior_run_id"] == bodies[0]["run_id"] for b in bodies[1:])
    assert rows(tmp_path, "SELECT COUNT(*) FROM payments") == [(1,)]
    assert rows(tmp_path, "SELECT COUNT(*) FROM runs") == [(4,)]
    # the gateway stub prints a "Paying ..." line to stderr only on a real call
    assert results[0].stderr.count("Paying ") == 1
    assert sum(r.stderr.count("Paying ") for r in results[1:]) == 0
    assert all("Traceback" not in r.stderr for r in results)


def test_replay_under_renamed_copy_and_other_format_pays_once(tmp_path):
    first = cli(tmp_path, CORPUS / "invoice_1011.txt")
    copy = tmp_path / "totally_different_name.txt"
    shutil.copy(CORPUS / "invoice_1011.txt", copy)
    renamed = cli(tmp_path, copy)
    other_format = cli(tmp_path, CORPUS / "invoice_1011.pdf")
    assert [json.loads(r.stdout)["status"] for r in (first, renamed, other_format)] == [
        "paid_mock",
        "duplicate",
        "duplicate",
    ]
    assert rows(tmp_path, "SELECT COUNT(*) FROM payments") == [(1,)]
    assert "Paying " not in renamed.stderr + other_format.stderr


def test_replay_of_revision_after_payment_never_pays_again(tmp_path):
    a = cli(tmp_path, CORPUS / "invoice_1004.json")
    b = cli(tmp_path, CORPUS / "invoice_1004_revised.json")
    c = cli(tmp_path, CORPUS / "invoice_1004_revised.json")
    assert json.loads(a.stdout)["status"] == "paid_mock"
    assert json.loads(b.stdout)["status"] == "needs_review"
    assert json.loads(c.stdout)["status"] == "duplicate"
    assert rows(tmp_path, "SELECT amount FROM payments") == [("1890.00",)]


def test_replay_of_unpayable_outcomes_creates_no_payment(tmp_path):
    for name in ("invoice_1002.txt", "invoice_1014.xml", "invoice_1013.json"):
        for _ in range(2):
            assert cli(tmp_path, CORPUS / name).returncode == 0
    assert rows(tmp_path, "SELECT COUNT(*) FROM payments") == [(0,)]


def test_failed_run_then_cli_retry_pays_once(tmp_path):
    bad = tmp_path / "invoice_x.json"
    bad.write_text('{"invoice_number": "INV-1004", ')
    assert cli(tmp_path, bad).returncode == 1
    good = cli(tmp_path, CORPUS / "invoice_1004.json")
    again = cli(tmp_path, CORPUS / "invoice_1004.json")
    assert json.loads(good.stdout)["status"] == "paid_mock"
    assert json.loads(again.stdout)["status"] == "duplicate"
    assert rows(tmp_path, "SELECT COUNT(*) FROM payments") == [(1,)]


def test_separate_databases_are_independent_but_each_pays_once(tmp_path):
    invoice = CORPUS / "invoice_1001.txt"
    for db in ("one.db", "two.db"):
        for _ in range(2):
            assert cli(tmp_path, invoice, db=db).returncode == 0
        assert rows(tmp_path, "SELECT COUNT(*) FROM payments", db=db) == [(1,)]


def test_explicit_offline_mode_flag_does_not_bypass_ledger(tmp_path):
    cli(tmp_path, CORPUS / "invoice_1001.txt")
    r = cli(tmp_path, CORPUS / "invoice_1001.txt", "--mode=offline")
    assert json.loads(r.stdout)["status"] == "duplicate"
    assert rows(tmp_path, "SELECT COUNT(*) FROM payments") == [(1,)]
