import grpc
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


def test_ping_failure_prints_the_stable_error_code(capsys, monkeypatch):
    from invoice_processing.reasoning import xai
    from tests.fakes.xai_client import FakeXaiClient, Raise

    monkeypatch.setenv("XAI_API_KEY", SENTINEL)
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    client = FakeXaiClient([Raise(grpc.StatusCode.UNAUTHENTICATED, f"bad key {SENTINEL}")])
    monkeypatch.setattr(xai, "real_client_factory", lambda settings: client)
    assert readiness.main(["--ping"]) == 2
    out = capsys.readouterr()
    assert "ping: failed (model_auth_error)" in out.out
    assert SENTINEL not in out.out + out.err


def test_ping_ok_uses_the_shared_client_factory(capsys, monkeypatch):
    from invoice_processing.reasoning import xai
    from tests.fakes.xai_client import FakeXaiClient, Parsed

    monkeypatch.setenv("XAI_API_KEY", SENTINEL)
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    client = FakeXaiClient([Parsed({})])  # sample() returns a plain answer without consuming
    monkeypatch.setattr(xai, "real_client_factory", lambda settings: client)
    assert readiness.main(["--ping"]) == 0
    assert "ping: ok (grok-test" in capsys.readouterr().out
    assert len(client.requests) == 1
