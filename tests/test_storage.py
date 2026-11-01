import sqlite3

import pytest

from invoice_processing import storage

TABLES = {
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
}


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows} - {"sqlite_sequence"}


def test_init_schema_creates_all_tables_and_is_idempotent(conn):
    assert table_names(conn) == TABLES
    assert conn.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
    before = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    storage.init_schema(conn)
    after = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    assert [tuple(r) for r in after] == [tuple(r) for r in before]


def test_init_schema_fills_in_missing_tables_without_dropping_data(db_path):
    c = storage.connect(db_path)
    c.execute(
        "CREATE TABLE inventory (item TEXT PRIMARY KEY, stock INTEGER NOT NULL CHECK (stock >= 0))"
    )
    c.execute("INSERT INTO inventory VALUES ('WidgetA', 15)")
    storage.init_schema(c)
    assert table_names(c) == TABLES
    assert c.execute("SELECT stock FROM inventory WHERE item='WidgetA'").fetchone()[0] == 15


def test_future_schema_version_is_refused(db_path):
    c = storage.connect(db_path)
    c.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION + 1}")
    with pytest.raises(storage.SchemaVersionError):
        storage.init_schema(c)


def test_connection_settings(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def _minimal_invoice_rows(conn):
    now = "2026-01-31T00:00:00Z"
    conn.execute("INSERT INTO sources VALUES ('s1','h1','a.txt','txt',10,NULL,NULL,?)", (now,))
    conn.execute(
        "INSERT INTO invoices VALUES ('i1','widgets inc.','1001',1,'processing',?,?)", (now, now)
    )
    conn.execute(
        "INSERT INTO runs (run_id, source_id, invoice_id, mode, status, started_at)"
        " VALUES ('r1','s1','i1','offline','received',?)",
        (now,),
    )


def test_one_payment_per_invoice_identity(conn):
    _minimal_invoice_rows(conn)
    row = ("p1", "i1", 1, "r1", "5000.00", "USD", "rcpt-1", "success", "2026-01-31T00:00:00Z")
    conn.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?)", row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?)", ("p2", *row[1:6], "rcpt-2", *row[7:])
        )


def test_write_transaction_rolls_back_on_error(conn):
    with pytest.raises(RuntimeError):
        with storage.write_transaction(conn):
            conn.execute("INSERT INTO inventory VALUES ('X', 1)")
            raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0


def test_get_stock(conn):
    conn.execute("INSERT INTO inventory VALUES ('WidgetA', 15), ('FakeItem', 0)")
    assert storage.get_stock(conn, ["WidgetA", "FakeItem", "Nope"]) == {
        "WidgetA": 15,
        "FakeItem": 0,
        "Nope": None,
    }
    assert storage.get_stock(conn, []) == {}


def test_get_stock_is_parameterized(conn):
    conn.execute("INSERT INTO inventory VALUES ('WidgetA', 15)")
    assert storage.get_stock(conn, ["WidgetA' OR '1'='1"]) == {"WidgetA' OR '1'='1": None}
