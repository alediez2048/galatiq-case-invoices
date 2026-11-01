import json

import main
import pytest

INVOICE = "data/invoices/invoice_1001.txt"


def _args(tmp_path, *extra, invoice=INVOICE, flag="--invoice_path"):
    return [
        f"{flag}={invoice}",
        f"--db={tmp_path / 'i.db'}",
        f"--events={tmp_path / 'e.jsonl'}",
        "--evaluation-date=2026-01-20",
        *extra,
    ]


def test_bare_command_pays_and_stdout_is_pure_json(tmp_path, capsys):
    code = main.main(_args(tmp_path))
    out, err = capsys.readouterr()
    assert code == 0
    assert json.loads(out)["status"] == "paid_mock"
    assert "Mode: offline simulation" in err and "Initialized" in err


def test_second_run_no_init_notice_and_duplicate(tmp_path, capsys):
    assert main.main(_args(tmp_path)) == 0
    capsys.readouterr()
    code = main.main(_args(tmp_path))
    out, err = capsys.readouterr()
    assert code == 0
    assert "Initialized" not in err
    assert json.loads(out)["status"] == "duplicate"


def test_dash_spelling_accepted(tmp_path, capsys):
    code = main.main(_args(tmp_path, flag="--invoice-path"))
    out, _ = capsys.readouterr()
    assert code == 0 and json.loads(out)["status"] == "paid_mock"


def test_output_option_writes_file_and_keeps_stdout_empty(tmp_path, capsys):
    target = tmp_path / "out" / "r.json"
    code = main.main(_args(tmp_path, f"--output={target}"))
    out, err = capsys.readouterr()
    assert code == 0 and out == ""
    assert json.loads(target.read_text())["status"] == "paid_mock"
    assert "status=paid_mock" in err


def test_live_mode_fails_clearly_and_touches_nothing(tmp_path, capsys):
    code = main.main(_args(tmp_path, "--mode=live"))
    out, err = capsys.readouterr()
    assert code == 2 and out == ""
    assert "not available" in err and not (tmp_path / "i.db").exists()


def test_missing_file_is_usage_error(tmp_path, capsys):
    code = main.main(_args(tmp_path, invoice=str(tmp_path / "nope.txt")))
    out, err = capsys.readouterr()
    assert code == 2 and out == ""
    assert "not_found" in err and not (tmp_path / "i.db").exists()


def test_bad_evaluation_date_is_usage_error(tmp_path, capsys):
    argv = [a for a in _args(tmp_path) if not a.startswith("--evaluation-date")]
    code = main.main([*argv, "--evaluation-date=not-a-date"])
    _, err = capsys.readouterr()
    assert code == 2 and "evaluation-date" in err and not (tmp_path / "i.db").exists()


def test_failed_run_exits_nonzero(tmp_path, capsys):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe\x00\xff invalid \x80\x81")
    code = main.main(_args(tmp_path, invoice=str(bad)))
    out, _ = capsys.readouterr()
    assert code == 1
    assert json.loads(out)["status"] == "failed"


def test_help_lists_every_option(capsys):
    with pytest.raises(SystemExit):
        main.main(["--help"])
    out = capsys.readouterr().out
    for opt in ["--invoice_path", "--mode", "--db", "--output", "--events", "--evaluation-date"]:
        assert opt in out


def test_install_network_guard_blocks_sockets(monkeypatch):
    import socket

    monkeypatch.setattr(socket.socket, "connect", socket.socket.connect)
    monkeypatch.setattr(socket, "create_connection", socket.create_connection)
    main._install_network_guard()
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.create_connection(("example.com", 80))


def test_stale_schema_database_fails_cleanly(tmp_path, capsys):
    import sqlite3

    db = tmp_path / "i.db"
    c = sqlite3.connect(db)
    c.execute("PRAGMA user_version=2")
    c.execute("CREATE TABLE t (x)")
    c.commit()
    c.close()
    code = main.main(_args(tmp_path))
    out, err = capsys.readouterr()
    assert code == 2 and out == ""
    assert "error:" in err and "older" in err
    assert "Traceback" not in err


def test_non_sqlite_database_fails_cleanly(tmp_path, capsys):
    (tmp_path / "i.db").write_text("this is not a sqlite database, just text " * 20)
    code = main.main(_args(tmp_path))
    out, err = capsys.readouterr()
    assert code == 2 and out == ""
    assert "error:" in err and "Traceback" not in err
