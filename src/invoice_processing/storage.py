"""SQLite schema, connections, transactions, and read-only inventory lookup.

Money columns hold decimal strings; timestamps are ISO-8601 UTC text.
"""

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

# 4: identity keys and normalization changed meaning (Phase 2); no DDL change.
# 5: runs.mode_switch_of (Phase 3).
SCHEMA_VERSION = 5


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
        mode_switch_of TEXT REFERENCES runs(run_id),
        prior_run_id TEXT REFERENCES runs(run_id),
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
        final_decision TEXT NOT NULL CHECK (final_decision IN
            ('approved', 'rejected', 'needs_review', 'awaiting_human_approval')),
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
        created_at TEXT NOT NULL,
        FOREIGN KEY (invoice_id, from_version) REFERENCES invoice_versions(invoice_id, version),
        FOREIGN KEY (invoice_id, to_version) REFERENCES invoice_versions(invoice_id, version))""",
    """CREATE TABLE IF NOT EXISTS human_reviews (
        review_id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
        version INTEGER NOT NULL,
        action TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        reason TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (invoice_id, version) REFERENCES invoice_versions(invoice_id, version))""",
    """CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL UNIQUE REFERENCES invoices(invoice_id),
        version INTEGER NOT NULL,
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        amount TEXT NOT NULL,
        currency TEXT NOT NULL,
        receipt_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (invoice_id, version) REFERENCES invoice_versions(invoice_id, version))""",
    """CREATE TABLE IF NOT EXISTS audit_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT REFERENCES runs(run_id),
        invoice_id TEXT REFERENCES invoices(invoice_id),
        version_id TEXT REFERENCES invoice_versions(version_id),
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
    if 0 < version < SCHEMA_VERSION:
        # CREATE TABLE IF NOT EXISTS never alters an existing table, so accepting an older
        # database would fail later with "no such column". There are no migrations yet.
        raise SchemaVersionError(
            f"database schema version {version} is older than {SCHEMA_VERSION}; "
            "recreate the database (e.g. seed --fresh to a new path)"
        )
    with write_transaction(conn):
        for statement in _DDL:
            conn.execute(statement)
        if version == 0:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One atomic write. Only the outermost caller opens it; helpers that write take an open
    transaction from their caller instead of nesting another one."""
    if conn.in_transaction:
        raise RuntimeError("write_transaction is for the outermost caller only; already open")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


@contextmanager
def atomic(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Join the caller's open transaction, or open one if none is active."""
    if conn.in_transaction:
        yield conn
    else:
        with write_transaction(conn):
            yield conn


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


def inventory_items(conn: sqlite3.Connection) -> list[str]:
    return [row["item"] for row in conn.execute("SELECT item FROM inventory ORDER BY item")]
