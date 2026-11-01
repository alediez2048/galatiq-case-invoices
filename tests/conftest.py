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
