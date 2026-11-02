"""Shared helpers for the robustness campaign (P6-01, offline part)."""

import sqlite3
from datetime import date
from pathlib import Path

from invoice_processing import payments, seed, storage
from invoice_processing.codes import ExecutionMode
from invoice_processing.storage import connect

CORPUS = Path("data/invoices")
FIXTURES = Path("tests/fixtures/robustness")
EVAL = date(2026, 1, 31)
OFF = ExecutionMode.offline


def fresh_db(tmp_path: Path, name: str = "r.db") -> Path:
    db = tmp_path / name
    c = connect(db)
    storage.init_schema(c)
    seed.seed_inventory(c)
    c.close()
    return db


def query(db: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    c = connect(db)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def payment_count(db: Path) -> int:
    return query(db, "SELECT COUNT(*) FROM payments")[0][0]


class PaymentSpy:
    """Counts calls to the mock payment gateway (the only code path that moves money)."""

    def __init__(self, monkeypatch):
        self.keys: list[str] = []
        real = payments.mock_payment

        def counting(*args, **kwargs):
            self.keys.append(kwargs.get("idempotency_key"))
            return real(*args, **kwargs)

        monkeypatch.setattr(payments, "mock_payment", counting)
