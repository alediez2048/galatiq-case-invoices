"""Run every file in data/invoices/ through the real CLI (offline) into one shared ledger.

    uv run python scripts/demo_run_all.py --db demo-offline.db [--evaluation-date 2026-01-31]
                                          [--order forward|reverse]

The database must already exist (create it with scripts/demo_setup.py). Subprocesses run
with INVOICE_NETWORK_GUARD=1 and --mode offline, so nothing can reach the network.
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVOICE_DIR = ROOT / "data" / "invoices"


def run_one(path: Path, db: Path, evaluation_date: str, events: Path) -> dict:
    """Run the CLI on one file; return the parsed result JSON plus the exit code."""
    env = {**os.environ, "INVOICE_NETWORK_GUARD": "1"}
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "main.py"),
            f"--invoice_path={path}",
            "--mode",
            "offline",
            "--db",
            str(db),
            "--evaluation-date",
            evaluation_date,
            "--events",
            str(events),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = None
    return {
        "file": path.name,
        "returncode": proc.returncode,
        "result": result,
        "stderr": proc.stderr,
    }


def gating_codes(result: dict) -> list[str]:
    seen: list[str] = []
    for f in result["findings"]:
        if f["severity"] in ("blocker", "review") and f["code"] not in seen:
            seen.append(f["code"])
    return seen


def summarize(runs: list[dict]) -> list[dict]:
    """Turn raw CLI runs into table rows."""
    file_by_run = {r["result"]["run_id"]: r["file"] for r in runs if r["result"]}
    rows = []
    for r in runs:
        res = r["result"]
        if res is None or r["returncode"] != 0 or res["status"] == "failed":
            rows.append(
                {
                    "file": r["file"],
                    "status": "FAILED",
                    "paid": None,
                    "reasons": [(res or {}).get("error_message") or r["stderr"].strip()[-80:]],
                    "duplicate_of": None,
                    "ok": False,
                }
            )
            continue
        paid = res["receipt"]["amount"] if res["status"] == "paid_mock" and res["receipt"] else None
        dup = file_by_run.get(res["prior_run_id"]) if res["status"] == "duplicate" else None
        rows.append(
            {
                "file": r["file"],
                "status": res["status"],
                "paid": paid,
                "reasons": gating_codes(res),
                "duplicate_of": dup,
                "ok": True,
            }
        )
    return rows


def ledger_totals(db: Path) -> dict:
    conn = sqlite3.connect(db)
    try:
        amounts = [Decimal(a) for (a,) in conn.execute("SELECT amount FROM payments")]
        return {
            "runs": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            "unique_invoices": conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0],
            "payments": len(amounts),
            "paid_total": sum(amounts, Decimal("0")),
        }
    finally:
        conn.close()


def format_table(rows: list[dict]) -> str:
    headers = ("file", "status", "paid (USD)", "reasons", "duplicate of")
    body = [
        (
            r["file"],
            r["status"],
            f"{Decimal(r['paid']):,.2f}" if r["paid"] else "-",
            ", ".join(r["reasons"]) or "-",
            r["duplicate_of"] or "-",
        )
        for r in rows
    ]
    widths = [max(len(str(x[i])) for x in [headers, *body]) for i in range(len(headers))]

    def line(cells):
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths, strict=True)).rstrip()

    return "\n".join([line(headers), line(["-" * w for w in widths]), *map(line, body)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run all fixture invoices into one ledger.")
    parser.add_argument("--db", required=True, help="existing demo database (see demo_setup.py)")
    parser.add_argument("--evaluation-date", default="2026-01-31")
    parser.add_argument("--order", choices=["forward", "reverse"], default="forward")
    args = parser.parse_args(argv)
    db = Path(args.db)
    if not db.exists():
        print(
            f"error: {db} does not exist; run scripts/demo_setup.py --db {db} first",
            file=sys.stderr,
        )
        return 2
    files = sorted(p for p in INVOICE_DIR.iterdir() if p.is_file())
    if args.order == "reverse":
        files.reverse()
    with tempfile.TemporaryDirectory() as tmp:
        events = Path(tmp) / "events.jsonl"
        runs = [run_one(p, db, args.evaluation_date, events) for p in files]
    rows = summarize(runs)
    print(format_table(rows))
    t = ledger_totals(db)
    print()
    print(f"documents processed : {len(files)}")
    print(f"runs in ledger      : {t['runs']}")
    print(f"unique invoices     : {t['unique_invoices']}")
    print(f"payments            : {t['payments']}")
    print(f"mock-paid total     : USD {t['paid_total']:,.2f}")
    failed = [r for r in rows if not r["ok"]]
    for r in failed:
        print(f"FAILED {r['file']}: {'; '.join(r['reasons'])}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
