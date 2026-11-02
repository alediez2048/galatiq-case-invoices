"""In-place upgrade from the immediately previous schema version (Decision 4)."""

import sqlite3
from pathlib import Path

import pytest

from invoice_processing import storage

DUMP = Path(__file__).parent / "fixtures" / "review" / "previous_schema.sql"
TABLES = [
    "inventory",
    "sources",
    "invoices",
    "invoice_versions",
    "runs",
    "findings",
    "decisions",
    "corrections",
    "human_reviews",
    "payments",
    "audit_events",
    "idempotency_keys",
]


def load_dump(tmp_path, dump=DUMP):
    conn = storage.connect(tmp_path / "previous.db")
    conn.executescript(dump.read_text())
    conn.execute("PRAGMA foreign_keys = ON")  # the dump switches it off
    return conn


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def columns(conn, table):
    return [tuple(r) for r in conn.execute(f"PRAGMA table_info({table})")]


def triggers(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' ORDER BY name")
    return [r[0] for r in rows]


def test_fixture_is_the_previous_version():
    text = DUMP.read_text()
    assert f"PRAGMA user_version={storage.SCHEMA_VERSION - 1};" in text
    assert "'extracted'" in text and "version_status" not in text


def test_previous_version_db_upgrades_without_data_loss(tmp_path):
    conn = load_dump(tmp_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION - 1
    before = {t: count(conn, t) for t in TABLES}
    assert before["payments"] == 1 and before["invoice_versions"] == 2
    payload_before = conn.execute(
        "SELECT version_id, payload_json FROM invoice_versions ORDER BY version_id"
    ).fetchall()
    storage.init_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
    assert {t: count(conn, t) for t in TABLES} == before
    payload_after = conn.execute(
        "SELECT version_id, payload_json FROM invoice_versions ORDER BY version_id"
    ).fetchall()
    assert [tuple(r) for r in payload_after] == [tuple(r) for r in payload_before]
    assert {r[0] for r in conn.execute("SELECT DISTINCT origin FROM invoice_versions")} == {
        "source"
    }
    assert {r[0] for r in conn.execute("SELECT DISTINCT version_status FROM invoice_versions")} == {
        "current"
    }
    assert {r[0] for r in conn.execute("SELECT DISTINCT trigger FROM runs")} == {"submission"}
    assert {r[0] for r in conn.execute("SELECT DISTINCT review_of FROM runs")} == {None}
    with pytest.raises(sqlite3.DatabaseError, match="immutable:payments"):
        with storage.write_transaction(conn):
            conn.execute("DELETE FROM payments")
    storage.init_schema(conn)  # a second start is a no-op
    assert {t: count(conn, t) for t in TABLES} == before


def test_migrated_schema_matches_a_fresh_one(tmp_path, conn):
    migrated = load_dump(tmp_path)
    storage.init_schema(migrated)
    for table in TABLES:
        assert columns(migrated, table) == columns(conn, table), table
    assert triggers(migrated) == triggers(conn)
    fks = {t: [tuple(r) for r in conn.execute(f"PRAGMA foreign_key_list({t})")] for t in TABLES}
    assert {
        t: [tuple(r) for r in migrated.execute(f"PRAGMA foreign_key_list({t})")] for t in TABLES
    } == fks


def test_failed_migration_leaves_the_previous_version(tmp_path, monkeypatch):
    conn = load_dump(tmp_path)
    monkeypatch.setattr(storage, "_TRIGGERS", ("CREATE TRIGGER broken",))
    with pytest.raises(sqlite3.DatabaseError):
        storage.init_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION - 1
    assert "version_status" not in {r[1] for r in columns(conn, "invoice_versions")}
    assert {r[0] for r in conn.execute("SELECT DISTINCT origin FROM invoice_versions")} == {
        "extracted"
    }


def test_two_versions_back_still_refused(db_path):
    c = storage.connect(db_path)
    c.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION - 2}")
    with pytest.raises(storage.SchemaVersionError, match="older"):
        storage.init_schema(c)
