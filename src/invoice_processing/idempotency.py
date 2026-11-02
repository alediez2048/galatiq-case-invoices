"""Stored responses for idempotent HTTP submissions (table ``idempotency_keys``)."""

import sqlite3

from invoice_processing import ledger, storage


def lookup(conn: sqlite3.Connection, key: str, endpoint: str) -> str | None:
    row = conn.execute(
        "SELECT response_json FROM idempotency_keys WHERE key = ? AND endpoint = ?",
        (key, endpoint),
    ).fetchone()
    return None if row is None else row["response_json"]


def remember(conn: sqlite3.Connection, key: str, endpoint: str, response_json: str) -> None:
    with storage.atomic(conn):
        conn.execute(
            "INSERT OR IGNORE INTO idempotency_keys (key, endpoint, response_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (key, endpoint, response_json, ledger.utcnow()),
        )
