"""Demo scripts: setup refuses existing DBs; run-all reproduces the shared-ledger outcomes."""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from tests.test_acceptance import CASES

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


demo_setup = _load("demo_setup")
demo_run_all = _load("demo_run_all")


def test_setup_creates_seeded_db_and_refuses_existing(tmp_path, capsys):
    db = tmp_path / "d.db"
    assert demo_setup.main(["--db", str(db)]) == 0
    stock = dict(sqlite3.connect(db).execute("SELECT item, stock FROM inventory").fetchall())
    assert stock == {"WidgetA": 15, "WidgetB": 10, "GadgetX": 5, "FakeItem": 0}

    conn = sqlite3.connect(db)
    conn.execute("UPDATE inventory SET stock = 1 WHERE item = 'WidgetA'")
    conn.commit()
    conn.close()
    before = db.read_bytes()
    assert demo_setup.main(["--db", str(db)]) == 2
    assert "already exists" in capsys.readouterr().err
    assert db.read_bytes() == before


def test_run_all_requires_existing_db(tmp_path):
    assert demo_run_all.main(["--db", str(tmp_path / "missing.db")]) == 2


@pytest.fixture(scope="module")
def run_all(tmp_path_factory):
    db = tmp_path_factory.mktemp("demo") / "all.db"
    assert demo_setup.main(["--db", str(db)]) == 0
    files = sorted(p for p in demo_run_all.INVOICE_DIR.iterdir() if p.is_file())
    events = tmp_path_factory.mktemp("ev") / "events.jsonl"
    runs = [demo_run_all.run_one(p, db, "2026-01-31", events) for p in files]
    return db, demo_run_all.summarize(runs), demo_run_all.ledger_totals(db), len(files)


def test_run_all_totals(run_all):
    db, rows, totals, n = run_all
    assert all(r["ok"] for r in rows)
    assert n == 20 and totals["runs"] == 20
    assert totals["payments"] == 7
    assert totals["unique_invoices"] == 16
    # no identity paid twice
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(DISTINCT invoice_id) FROM payments").fetchone()[0] == 7
    assert c.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 7


def test_run_all_statuses_match_acceptance(run_all):
    _, rows, _, _ = run_all
    by_file = {r["file"]: r for r in rows}
    # fixtures whose identity is unique in the corpus behave exactly as in the acceptance suite
    shared = {"invoice_1004.json", "invoice_1004_revised.json"}
    dup_groups = {"invoice_1011", "invoice_1012", "invoice_1013"}
    for name, (status, paid, blockers, _) in CASES.items():
        if name in shared or name.rsplit(".", 1)[0] in dup_groups:
            continue
        row = by_file[name]
        assert row["status"] == status, name
        assert row["paid"] == paid, name
        assert blockers <= set(row["reasons"]), name
    assert by_file["invoice_1004.json"]["status"] == "paid_mock"
    assert by_file["invoice_1004_revised.json"]["status"] == "needs_review"
    assert by_file["invoice_1004_revised.json"]["reasons"] == ["revision_after_payment"]
    for twin, first in [
        ("invoice_1011.txt", "invoice_1011.pdf"),
        ("invoice_1012.txt", "invoice_1012.pdf"),
        ("invoice_1013.pdf", "invoice_1013.json"),
    ]:
        assert by_file[twin]["status"] == "duplicate"
        assert by_file[twin]["duplicate_of"] == first
        assert by_file[twin]["paid"] is None
