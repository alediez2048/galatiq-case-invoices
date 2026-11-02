"""SQLite schema, connections, transactions, and read-only inventory lookup.

Money columns hold decimal strings; timestamps are ISO-8601 UTC text.
"""

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

# 4: identity keys and normalization changed meaning (Phase 2); no DDL change.
# 5: diverged on two branches: runs.mode_switch_of (Phase 3) and idempotency_keys (P5-01).
# 6: both of the above. A v5 database may hold only one of them, so it is refused too.
# 7: human review (Phase 4): version_status, run trigger/review_of, review-row run links,
#    immutability triggers. init_schema upgrades a v6 database in place.
SCHEMA_VERSION = 7


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
        version_status TEXT NOT NULL DEFAULT 'current'
            CHECK (version_status IN ('current','superseded')),
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
        finished_at TEXT,
        trigger TEXT NOT NULL DEFAULT 'submission',
        review_of TEXT REFERENCES runs(run_id))""",
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
        run_id TEXT REFERENCES runs(run_id),
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
        run_id TEXT REFERENCES runs(run_id),
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
    """CREATE TABLE IF NOT EXISTS idempotency_keys (
        key TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        response_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (key, endpoint))""",
)


# Columns added by schema 7, in the order the fresh DDL above declares them (each at the end
# of its table), so a migrated table matches a fresh one column for column.
_ADDED_COLUMNS = (
    (
        "invoice_versions",
        "version_status",
        "TEXT NOT NULL DEFAULT 'current' CHECK (version_status IN ('current','superseded'))",
    ),
    ("runs", "trigger", "TEXT NOT NULL DEFAULT 'submission'"),
    ("runs", "review_of", "TEXT REFERENCES runs(run_id)"),
    ("corrections", "run_id", "TEXT REFERENCES runs(run_id)"),
    ("human_reviews", "run_id", "TEXT REFERENCES runs(run_id)"),
)

# Review history is append-only (Decision 2): UPDATE and DELETE are refused on these tables,
# except for the three narrow updates below. Each exception compares every other column with
# IS NOT (NULL-safe), so it permits a change of that one column only.
IMMUTABLE_TABLES = (
    "sources",
    "invoice_versions",
    "corrections",
    "human_reviews",
    "payments",
    "audit_events",
    "findings",
    "decisions",
)
_SOURCE_COLUMNS = (
    "source_id",
    "content_hash",
    "original_name",
    "format",
    "size_bytes",
    "parser_version",
    "created_at",
)
_VERSION_COLUMNS = (
    "version_id",
    "invoice_id",
    "version",
    "parent_version",
    "origin",
    "source_id",
    "semantic_hash",
    "payload_json",
    "created_at",
)
_PAYMENT_COLUMNS = (
    "payment_id",
    "invoice_id",
    "version",
    "amount",
    "currency",
    "receipt_id",
    "status",
    "created_at",
)


def _changed(columns: tuple[str, ...]) -> str:
    return " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in columns)


_UPDATE_ALLOWED_UNLESS = {
    # (b) the decoded source text is filled in once
    "sources": f"{_changed(_SOURCE_COLUMNS)} "
    "OR OLD.extracted_text IS NOT NULL OR NEW.extracted_text IS NULL",
    # (a) a current version is superseded, never the reverse
    "invoice_versions": f"{_changed(_VERSION_COLUMNS)} "
    "OR OLD.version_status IS NOT 'current' OR NEW.version_status IS NOT 'superseded'",
    # (c) the Phase 3 crash replay re-points the payment from a payer that failed
    "payments": f"{_changed(_PAYMENT_COLUMNS)} OR NEW.run_id IS OLD.run_id "
    "OR (SELECT status FROM runs WHERE run_id = OLD.run_id) IS NOT 'failed'",
}


def _immutability_triggers() -> tuple[str, ...]:
    statements = []
    for table in IMMUTABLE_TABLES:
        abort = f"BEGIN SELECT RAISE(ABORT, 'immutable:{table}'); END"
        when = _UPDATE_ALLOWED_UNLESS.get(table)
        guard = f" WHEN {when}" if when else ""
        statements.append(
            f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_update "
            f"BEFORE UPDATE ON {table} FOR EACH ROW{guard} {abort}"
        )
        statements.append(
            f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_delete "
            f"BEFORE DELETE ON {table} FOR EACH ROW {abort}"
        )
    return tuple(statements)


_TRIGGERS = _immutability_triggers()


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
    upgrade = version == SCHEMA_VERSION - 1
    if 0 < version < SCHEMA_VERSION and not upgrade:
        # CREATE TABLE IF NOT EXISTS never alters an existing table, so accepting an older
        # database would fail later with "no such column". Only the previous version has a
        # migration.
        raise SchemaVersionError(
            f"database schema version {version} is older than {SCHEMA_VERSION}; "
            "recreate the database (e.g. seed --fresh to a new path)"
        )
    with write_transaction(conn):
        if upgrade:
            _add_columns(conn)
        for statement in _DDL:
            conn.execute(statement)
        if upgrade:
            # Decision 5: version origins are source | correction; before the triggers exist.
            conn.execute("UPDATE invoice_versions SET origin = 'source' WHERE origin = 'extracted'")
        for statement in _TRIGGERS:
            conn.execute(statement)
        if version != SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _add_columns(conn: sqlite3.Connection) -> None:
    """Schema 6 -> 7, inside the caller's transaction. A table that does not exist yet is
    created afterwards by the fresh DDL, so only existing tables are altered."""
    for table, column, decl in _ADDED_COLUMNS:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if existing and column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


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
