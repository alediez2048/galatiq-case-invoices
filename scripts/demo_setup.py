"""Create a fresh, seeded demo database. Refuses to touch an existing path.

uv run python scripts/demo_setup.py --db demo-offline.db
"""

import argparse
import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from invoice_processing import storage  # noqa: E402
from invoice_processing.seed import SEED_ITEMS, seed_inventory  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a fresh seeded demo database.")
    parser.add_argument("--db", required=True, help="path of the new database (must not exist)")
    args = parser.parse_args(argv)
    path = Path(args.db)
    if path.exists() or path.is_symlink():
        print(
            f"error: {path} already exists; demo_setup never modifies an existing database. "
            "Choose a new path or delete it yourself.",
            file=sys.stderr,
        )
        return 2
    conn = storage.connect(path)
    try:
        storage.init_schema(conn)
        seed_inventory(conn)
    finally:
        conn.close()
    print(f"Created {path} (schema initialized, inventory seeded)")
    for item, stock in SEED_ITEMS.items():
        print(f"  {item}: {stock}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
