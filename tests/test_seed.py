from invoice_processing import seed, storage


def test_seed_twice_reports_unchanged(conn):
    first = seed.seed_inventory(conn)
    assert sorted(first.inserted) == ["FakeItem", "GadgetX", "WidgetA", "WidgetB"]
    second = seed.seed_inventory(conn)
    assert second.inserted == [] and sorted(second.unchanged) == sorted(seed.SEED_ITEMS)
    assert storage.get_stock(conn, seed.SEED_ITEMS) == seed.SEED_ITEMS


def test_seed_keeps_existing_values_and_reports_difference(conn):
    seed.seed_inventory(conn)
    conn.execute("UPDATE inventory SET stock = 99 WHERE item = 'WidgetA'")
    report = seed.seed_inventory(conn)
    assert report.differing == [("WidgetA", 99, 15)]
    assert storage.get_stock(conn, ["WidgetA"]) == {"WidgetA": 99}


def test_cli_creates_and_seeds(db_path, capsys):
    assert seed.main(["--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert "Inserted:" in out and "WidgetA" in out
    c = storage.connect(db_path)
    assert storage.get_stock(c, ["GadgetX"]) == {"GadgetX": 5}


def test_cli_fresh_refuses_existing_path(db_path, capsys):
    db_path.write_bytes(b"not a database")
    assert seed.main(["--db", str(db_path), "--fresh"]) == 2
    assert db_path.read_bytes() == b"not a database"
    assert "exists" in capsys.readouterr().err


def test_cli_warns_on_difference(db_path, capsys):
    seed.main(["--db", str(db_path)])
    c = storage.connect(db_path)
    c.execute("UPDATE inventory SET stock = 99 WHERE item = 'WidgetA'")
    c.close()
    seed.main(["--db", str(db_path)])
    assert "WARNING: WidgetA stock 99 differs from seed 15" in capsys.readouterr().out
