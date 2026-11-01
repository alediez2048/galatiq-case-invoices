"""SQLite schema, connections, transactions, and read-only inventory lookup.

Money columns hold decimal strings; timestamps are ISO-8601 UTC text.
"""

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    pass


_DDL = (
    """CREATE TABLE IF NOT EXISTS inventory (
        item TEXT PRIMARY KEY,
        stock INTEGER NOT NULL CHECK (stock >= 0))""",
    """CREATE TABLE IF NOT EXISTS sources (
        source_id TEXT PRIMARY KEY,
        content_hash TEXT NOT NULL UNIQUE,
        original_name TEXT NOT NULL,
        format TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        parser_version TEXT,
        extracted_text TEXT,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS invoices (
        invoice_id TEXT PRIMARY KEY,
        vendor_key TEXT NOT NULL,
        invoice_number_key TEXT NOT NULL,
        current_version INTEGER,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (vendor_key, invoice_number_key))""",
    """CREATE TABLE IF NOT EXISTS invoice_versions (
        version_id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
        version INTEGER NOT NULL,
        parent_version INTEGER,
        origin TEXT NOT NULL,
        source_id TEXT NOT NULL REFERENCES sources(source_id),
        semantic_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (invoice_id, version))""",
    """CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES sources(source_id),
        invoice_id TEXT REFERENCES invoices(invoice_id),
        version_id TEXT REFERENCES invoice_versions(version_id),
        mode TEXT NOT NULL,
        status TEXT NOT NULL,
        stage TEXT,
        error_code TEXT,
        error_message TEXT,
        retry_of TEXT REFERENCES runs(run_id),
        evaluation_date TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS findings (
        finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        version_id TEXT REFERENCES invoice_versions(version_id),
        code TEXT NOT NULL,
        severity TEXT NOT NULL,
        payload_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS decisions (
        decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
        version_id TEXT REFERENCES invoice_versions(version_id),
        payload_json TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        mode TEXT NOT NULL,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS corrections (
        correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
        from_version INTEGER NOT NULL,
        to_version INTEGER NOT NULL,
        field TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT NOT NULL,
        evidence_location TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS human_reviews (
        review_id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
        version INTEGER NOT NULL,
        action TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        reason TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL UNIQUE REFERENCES invoices(invoice_id),
        version INTEGER NOT NULL,
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        amount TEXT NOT NULL,
        currency TEXT NOT NULL,
        receipt_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS audit_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT REFERENCES runs(run_id),
        invoice_id TEXT REFERENCES invoices(invoice_id),
        version_id TEXT,
        stage TEXT NOT NULL,
        event TEXT NOT NULL,
        actor TEXT,
        payload_json TEXT,
        created_at TEXT NOT NULL)""",
)


def connect(path: str | Path) -> sqlite3.Connection:
    # isolation_level=None: no implicit transactions; writers use write_transaction().
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"database schema version {version} is newer than supported {SCHEMA_VERSION}"
        )
    with write_transaction(conn):
        for statement in _DDL:
            conn.execute(statement)
        if version == 0:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def get_stock(conn: sqlite3.Connection, items: Iterable[str]) -> dict[str, int | None]:
    names = list(dict.fromkeys(items))
    if not names:
        return {}
    placeholders = ",".join("?" * len(names))
    rows = conn.execute(
        f"SELECT item, stock FROM inventory WHERE item IN ({placeholders})", names
    ).fetchall()
    found = {row["item"]: row["stock"] for row in rows}
    return {name: found.get(name) for name in names}
