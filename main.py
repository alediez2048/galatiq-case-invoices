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
    # gRPC (used by xai_sdk) opens sockets in its C core, bypassing the socket module.
    try:
        import grpc
    except ImportError:
        return
    grpc.secure_channel = blocked  # type: ignore[assignment]
    grpc.insecure_channel = blocked  # type: ignore[assignment]
    try:
        import grpc.aio
    except ImportError:
        return
    grpc.aio.secure_channel = blocked  # type: ignore[assignment]
    grpc.aio.insecure_channel = blocked  # type: ignore[assignment]


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
from invoice_processing.reasoning.base import NoModelProvider  # noqa: E402
from invoice_processing.seed import seed_inventory  # noqa: E402
from invoice_processing.service import (  # noqa: E402
    RetryNeedsFile,
    RetryRefused,
    check_retry,
    process_invoice,
    retry_run,
)
from invoice_processing.storage import SchemaVersionError, connect, init_schema  # noqa: E402

DEFAULT_MODE = "offline"  # provisional; see docs/tickets/P1-09


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Process one invoice through the agent workflow.")
    p.add_argument(
        "--invoice_path",
        "--invoice-path",
        dest="invoice_path",
        default=None,
        help="path to the invoice file (required, except with --retry of a failed review run: "
        "a correction or an approve/decline run)",
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
        help="date used for due-date checks, YYYY-MM-DD (default: today; for --retry, the "
        "original run's date)",
    )
    p.add_argument(
        "--retry",
        metavar="RUN_ID",
        default=None,
        help="retry this failed run with the same --invoice_path, in the run's original mode "
        "(--mode is ignored); a failed correction or approve/decline run needs no "
        "--invoice_path, and an approve/decline run calls no model (no credentials needed)",
    )
    return p


def _print_mode_banner(mode: ExecutionMode, provider) -> None:
    if mode is ExecutionMode.offline:
        print("Mode: offline simulation", file=sys.stderr)
    else:
        # The model name is not a secret.
        print(
            f"Mode: live model ({getattr(provider, 'model', '?')})"
            " \u2014 invoice text will be sent to xAI",
            file=sys.stderr,
        )


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
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.invoice_path is None and args.retry is None:
        parser.error("the following arguments are required: --invoice_path")
    try:
        given = date.fromisoformat(args.evaluation_date) if args.evaluation_date else None
    except ValueError:
        print(
            f"error: invalid --evaluation-date {args.evaluation_date!r}; use YYYY-MM-DD",
            file=sys.stderr,
        )
        return 2
    if args.retry is not None:
        return _retry(args, given)
    evaluation_date = given or date.today()
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
    _print_mode_banner(mode, provider)
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
    return _finish(result, args)


def _retry(args: argparse.Namespace, evaluation_date: date | None) -> int:
    """--retry RUN_ID: the run's original mode is used; its provider loads only then. The
    original run's evaluation date applies unless --evaluation-date is given."""
    if not Path(args.db).exists():  # nothing to retry; do not create a database
        print("error: retry refused: unknown_run", file=sys.stderr)
        return 2
    try:
        target = check_retry(args.retry, args.invoice_path, args.db)
        print(f"Retrying run {target.run_id} (failed: {target.error_code})", file=sys.stderr)
        if target.trigger == "human_review":  # approve/decline: no model call, no key
            provider = NoModelProvider(target.mode)
            print(f"Mode: {target.mode.value} human review (no model call)", file=sys.stderr)
        else:
            provider = get_provider(target.mode)
            _print_mode_banner(target.mode, provider)
        events = configure_events(Path(args.events))
        result = retry_run(
            args.retry,
            args.invoice_path,
            args.db,
            evaluation_date or target.evaluation_date or date.today(),
            events,
            provider=provider,
        )
    except RetryNeedsFile:
        print("error: --invoice_path is required to retry this run", file=sys.stderr)
        return 2
    except RetryRefused as exc:
        receipt = f" (receipt {exc.receipt_id})" if exc.receipt_id else ""
        print(f"error: retry refused: {exc.reason}{receipt}", file=sys.stderr)
        return 2
    except ProviderUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except intake.IntakeError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except (SchemaVersionError, sqlite3.DatabaseError) as exc:
        print(f"error: database {args.db!r} cannot be used: {exc}", file=sys.stderr)
        return 2
    return _finish(result, args)


def _finish(result, args: argparse.Namespace) -> int:
    write_result(result, Path(args.output) if args.output else None)
    print(format_summary(result), file=sys.stderr)
    return 1 if result.status is RunStatus.failed else 0


if __name__ == "__main__":
    sys.exit(main())
