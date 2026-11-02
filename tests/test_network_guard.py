import socket
from pathlib import Path

import pytest


def test_getaddrinfo_blocked():
    with pytest.raises(RuntimeError, match="blocked"):
        socket.getaddrinfo("example.com", 443)


def test_connect_ex_blocked():
    with pytest.raises(RuntimeError, match="blocked"):
        socket.socket().connect_ex(("127.0.0.1", 9))


def test_network_is_blocked():
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.create_connection(("example.com", 80), timeout=1)


# --- live-marked tests are exempt from every guard (P3-10 smoke harness) -----------------

pytest_plugins = ["pytester"]

_CONFTEST = Path(__file__).with_name("conftest.py")

_PROBE = """
import os, socket
import grpc
import pytest
from invoice_processing import settings
from invoice_processing.reasoning import xai


def _guarded():
    return {
        "socket": socket.getaddrinfo.__name__ == "blocked",
        "grpc": grpc.secure_channel.__name__ == "blocked",
        "factory": xai.real_client_factory.__name__ == "blocked",
        "dotenv": settings.load_dotenv_file.__name__ == "<lambda>",
        "env": "XAI_MODEL" not in os.environ,
    }


@pytest.mark.live
def test_live():
    assert _guarded() == dict.fromkeys(_guarded(), False)


def test_plain():
    assert _guarded() == dict.fromkeys(_guarded(), True)
"""


def test_live_marked_tests_skip_every_guard_and_others_keep_them(pytester, monkeypatch):
    # A subprocess, so this test's own (active) guards do not leak into the probe run.
    monkeypatch.setenv("XAI_MODEL", "grok-probe")
    pytester.makeconftest(_CONFTEST.read_text())
    pytester.makepyfile(test_probe=_PROBE)
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-W", "ignore")
    result.assert_outcomes(passed=2)


def test_is_live_test_reads_the_marker():
    from tests.conftest import is_live_test

    class Node:
        def __init__(self, marked):
            self.marked = marked

        def get_closest_marker(self, name):
            return object() if self.marked and name == "live" else None

    assert is_live_test(Node(True)) is True
    assert is_live_test(Node(False)) is False


def test_smoke_harness_builds_its_provider_with_the_real_factory():
    from invoice_processing.reasoning import xai
    from invoice_processing.settings import LiveSettings
    from tests.live import test_live_smoke

    provider = test_live_smoke.live_provider(LiveSettings(api_key="sk-SENTINEL-123", model="m"))
    assert isinstance(provider, xai.XaiProvider)
    assert provider._client_factory is xai.real_client_factory  # looked up at call time
