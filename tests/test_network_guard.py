import socket

import pytest


def test_network_is_blocked():
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.create_connection(("example.com", 80), timeout=1)
