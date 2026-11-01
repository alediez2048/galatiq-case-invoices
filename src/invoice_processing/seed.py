"""Idempotent inventory seed. Inserts missing items; never overwrites existing stock."""

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from invoice_processing import storage

SEED_ITEMS: dict[str, int] = {"WidgetA": 15, "WidgetB": 10, "GadgetX": 5, "FakeItem": 0}


@dataclass
class SeedReport:
    inserted: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    differing: list[tuple[str, int, int]] = field(default_factory=list)  # (item, existing, seed)


def seed_inventory(conn: sqlite3.Connection) -> SeedReport:
    report = SeedReport()
    with storage.write_transaction(conn):
        existing = storage.get_stock(conn, SEED_ITEMS)
        for item, stock in SEED_ITEMS.items():
            current = existing[item]
            if current is None:
                conn.execute("INSERT INTO inventory (item, stock) VALUES (?, ?)", (item, stock))
                report.inserted.append(item)
            elif current == stock:
                report.unchanged.append(item)
            else:
                report.differing.append((item, current, stock))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the inventory database.")
    parser.add_argument("--db", default="inventory.db", help="SQLite database path")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="require that the database does not exist yet (for repeatable demo databases)",
    )
    args = parser.parse_args(argv)
    path = Path(args.db)
    if args.fresh and path.exists():
        print(f"error: {path} already exists; --fresh only creates new databases", file=sys.stderr)
        return 2

    conn = storage.connect(path)
    try:
        storage.init_schema(conn)
        report = seed_inventory(conn)
    finally:
        conn.close()

    print(f"Inserted: {', '.join(report.inserted) or 'none'}")
    print(f"Unchanged: {', '.join(report.unchanged) or 'none'}")
    for item, existing, seeded in report.differing:
        print(f"WARNING: {item} stock {existing} differs from seed {seeded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
