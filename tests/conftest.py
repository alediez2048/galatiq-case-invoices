import os
import socket
from pathlib import Path

import pytest

from invoice_processing import storage


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    c = storage.connect(db_path)
    storage.init_schema(c)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise RuntimeError("network access blocked in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


_LIVE_ENV = ("XAI_API_KEY", "XAI_MODEL", "XAI_TIMEOUT_SECONDS", "MODEL_CALL_BUDGET")


@pytest.fixture(autouse=True)
def no_grpc(request, monkeypatch):
    """gRPC sockets live in its C core, out of reach of `no_network`: block channel creation
    and the real xAI client factory. `@pytest.mark.real_xai_factory` keeps the real factory
    (channel creation stays blocked unless the test re-patches it itself)."""
    import grpc

    def blocked(*args, **kwargs):
        raise RuntimeError("network access blocked in tests")

    monkeypatch.setattr(grpc, "secure_channel", blocked)
    monkeypatch.setattr(grpc, "insecure_channel", blocked)
    if request.node.get_closest_marker("real_xai_factory") is None:
        monkeypatch.setattr("invoice_processing.reasoning.xai.real_client_factory", blocked)


@pytest.fixture(autouse=True)
def no_live_env(request, monkeypatch):
    """No test sees the developer's XAI_* settings or `.env`. Tests marked
    `@pytest.mark.real_dotenv` keep the real `.env` loader (they chdir to a tmp `.env`)."""
    for name in _LIVE_ENV:
        monkeypatch.delenv(name, raising=False)
    if request.node.get_closest_marker("real_dotenv") is None:
        monkeypatch.setattr("invoice_processing.settings.load_dotenv_file", lambda: None)
    yield
    for name in _LIVE_ENV:  # drop anything a real .env load wrote outside monkeypatch
        os.environ.pop(name, None)
