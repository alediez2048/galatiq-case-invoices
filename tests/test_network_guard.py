import socket

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
