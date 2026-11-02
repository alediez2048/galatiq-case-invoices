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
    "idempotency_keys",
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
    _version_row(conn)
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


def test_older_schema_version_is_refused(db_path):
    c = storage.connect(db_path)
    c.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION - 1}")
    with pytest.raises(storage.SchemaVersionError, match="older"):
        storage.init_schema(c)


def _version_row(conn):
    conn.execute(
        "INSERT INTO invoice_versions VALUES ('v1','i1',1,NULL,'extracted','s1','sh','{}',?)",
        ("2026-01-31T00:00:00Z",),
    )


@pytest.mark.parametrize("version", [1, 2])
def test_human_review_must_reference_existing_version(conn, version):
    _minimal_invoice_rows(conn)
    _version_row(conn)
    insert = (
        "INSERT INTO human_reviews (invoice_id, version, action, reviewer, reason,"
        " policy_version, created_at) VALUES ('i1', ?, 'approve', 'vp', 'ok', 'p1', 'now')"
    )
    if version == 1:
        conn.execute(insert, (version,))
    else:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, (version,))


def test_payment_must_reference_existing_version(conn):
    _minimal_invoice_rows(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO payments VALUES ('p1','i1',1,'r1','5000.00','USD','rcpt-1','success','n')"
        )


def test_decision_final_decision_is_queryable_and_checked(conn):
    _minimal_invoice_rows(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(decisions)")}
    assert "final_decision" in cols
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decisions (run_id, payload_json, final_decision, policy_version, mode,"
            " created_at) VALUES ('r1','{}','maybe','p1','offline','now')"
        )


def test_write_transaction_refuses_nesting(conn):
    with storage.write_transaction(conn):
        with pytest.raises(RuntimeError, match="outermost"):
            with storage.write_transaction(conn):
                pass
    assert not conn.in_transaction


def test_runs_have_prior_run_id(conn):
    assert "prior_run_id" in {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}


def test_atomic_joins_open_transaction(conn):
    with storage.write_transaction(conn):
        with storage.atomic(conn):
            conn.execute("INSERT INTO inventory VALUES ('X', 1)")
        assert conn.in_transaction
    assert not conn.in_transaction


def test_atomic_opens_and_rolls_back_alone(conn):
    with pytest.raises(RuntimeError):
        with storage.atomic(conn):
            conn.execute("INSERT INTO inventory VALUES ('X', 1)")
            raise RuntimeError
    assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0


def test_phase_1_schema_version_3_is_refused(db_path):
    assert storage.SCHEMA_VERSION == 6
    c = storage.connect(db_path)
    c.execute("PRAGMA user_version = 3")
    with pytest.raises(storage.SchemaVersionError):
        storage.init_schema(c)


def test_inventory_items_returns_all_names_sorted(conn):
    from invoice_processing.seed import seed_inventory

    seed_inventory(conn)
    assert storage.inventory_items(conn) == ["FakeItem", "GadgetX", "WidgetA", "WidgetB"]


def test_schema_v6_has_both_v5_branch_changes(conn):
    # v5 diverged: Phase 3 added runs.mode_switch_of, P5-01 added idempotency_keys.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}
    assert "mode_switch_of" in cols
    assert "idempotency_keys" in table_names(conn)


def test_schema_v5_database_from_either_branch_is_refused(db_path):
    assert storage.SCHEMA_VERSION == 6
    c = storage.connect(db_path)
    c.execute("PRAGMA user_version = 5")
    with pytest.raises(storage.SchemaVersionError, match="older"):
        storage.init_schema(c)
