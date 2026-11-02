"""CLI entry point: python main.py --invoice_path=data/invoices/invoice_1001.txt"""

import argparse
import os
import socket
import sqlite3
import sys
from datetime import date
from pathlib import Path

# Make `python main.py` work from a fresh clone even if the editable install is
# unavailable (e.g. macOS hides the .pth file inside iCloud-synced folders).
_SRC = str(Path(__file__).resolve().parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def _install_network_guard() -> None:
    """Block outbound sockets. TEST-ONLY: enabled by INVOICE_NETWORK_GUARD=1 so
    subprocess e2e tests can prove offline mode makes no network calls."""

    def blocked(*args, **kwargs):
        raise RuntimeError("network access blocked in tests")

    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.create_connection = blocked  # type: ignore[assignment]
    socket.socket.connect_ex = blocked  # type: ignore[method-assign]
    socket.getaddrinfo = blocked  # type: ignore[assignment]


if os.environ.get("INVOICE_NETWORK_GUARD") == "1":
    _install_network_guard()

from invoice_processing import intake  # noqa: E402
from invoice_processing.codes import ExecutionMode, RunStatus  # noqa: E402
from invoice_processing.observability import (  # noqa: E402
    configure_events,
    format_summary,
    write_result,
)
from invoice_processing.reasoning import ProviderUnavailable, get_provider  # noqa: E402
from invoice_processing.seed import seed_inventory  # noqa: E402
from invoice_processing.service import process_invoice  # noqa: E402
from invoice_processing.storage import SchemaVersionError, connect, init_schema  # noqa: E402

DEFAULT_MODE = "offline"  # provisional; see docs/tickets/P1-09


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Process one invoice through the agent workflow.")
    p.add_argument(
        "--invoice_path",
        "--invoice-path",
        dest="invoice_path",
        required=True,
        help="path to the invoice file (.txt; more formats in Phase 2)",
    )
    p.add_argument(
        "--mode",
        choices=[m.value for m in ExecutionMode],
        default=DEFAULT_MODE,
        help="reasoning mode: offline simulation or live LLM (default: %(default)s)",
    )
    p.add_argument(
        "--db", default="inventory.db", help="SQLite database path (default: %(default)s)"
    )
    p.add_argument(
        "--output", default=None, help="write the result JSON to this file instead of stdout"
    )
    p.add_argument(
        "--events",
        default="output/events.jsonl",
        help="JSON-lines event log path (default: %(default)s)",
    )
    p.add_argument(
        "--evaluation-date",
        default=None,
        help="date used for due-date checks, YYYY-MM-DD (default: today)",
    )
    return p


def _ensure_database(path: str) -> None:
    exists = Path(path).exists()
    conn = connect(path)
    try:
        if not exists or conn.execute("PRAGMA user_version").fetchone()[0] == 0:
            init_schema(conn)
            seed_inventory(conn)
            print(f"Initialized {path} and seeded inventory", file=sys.stderr)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evaluation_date = (
            date.fromisoformat(args.evaluation_date) if args.evaluation_date else date.today()
        )
    except ValueError:
        print(
            f"error: invalid --evaluation-date {args.evaluation_date!r}; use YYYY-MM-DD",
            file=sys.stderr,
        )
        return 2
    mode = ExecutionMode(args.mode)
    try:
        provider = get_provider(mode)
    except ProviderUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        intake.read_source(args.invoice_path)  # validate before touching the database
    except intake.IntakeError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    if mode is ExecutionMode.offline:
        print("Mode: offline simulation", file=sys.stderr)
    else:
        # Only reached once a live provider exists (Task 2); the model name is not a secret.
        print(
            f"Mode: live model ({getattr(provider, 'model', '?')})"
            " \u2014 invoice text will be sent to xAI",
            file=sys.stderr,
        )
    try:
        _ensure_database(args.db)
        events = configure_events(Path(args.events))
        result = process_invoice(
            args.invoice_path, mode, args.db, evaluation_date, events, provider=provider
        )
    except intake.IntakeError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except (SchemaVersionError, sqlite3.DatabaseError) as exc:
        print(f"error: database {args.db!r} cannot be used: {exc}", file=sys.stderr)
        return 2
    write_result(result, Path(args.output) if args.output else None)
    print(format_summary(result), file=sys.stderr)
    return 1 if result.status is RunStatus.failed else 0


if __name__ == "__main__":
    sys.exit(main())
