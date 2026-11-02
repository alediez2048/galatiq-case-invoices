import pytest

from invoice_processing import readiness

SENTINEL = "sk-SENTINEL-123"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here
    for k in ("XAI_API_KEY", "XAI_MODEL", "XAI_TIMEOUT_SECONDS", "MODEL_CALL_BUDGET"):
        monkeypatch.delenv(k, raising=False)


def test_not_ready_without_env(capsys):
    assert readiness.main([]) == 2
    out = capsys.readouterr().out
    assert "XAI_API_KEY: missing" in out and "XAI_MODEL: missing" in out


def test_ready_never_prints_value(capsys, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", SENTINEL)
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    assert readiness.main([]) == 0
    out = capsys.readouterr()
    assert "XAI_API_KEY: set" in out.out and "XAI_MODEL: grok-test" in out.out
    assert SENTINEL not in out.out + out.err


def test_bad_number_not_ready(capsys, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", SENTINEL)
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    monkeypatch.setenv("MODEL_CALL_BUDGET", "zero")
    assert readiness.main([]) == 2
    out = capsys.readouterr()
    assert SENTINEL not in out.out + out.err
