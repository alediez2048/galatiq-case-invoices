# Development

## Prerequisites

- Python 3.12, managed by [uv](https://docs.astral.sh/uv/) (`.python-version` pins 3.12).
- Node.js 22 is reserved for the Phase 5 frontend; not needed yet.

## Setup

```bash
uv sync
```

Creates `.venv/` with the package installed in editable mode plus the dev tools.

## Run tests

```bash
uv run pytest
```

## Run

```bash
python main.py --invoice_path=data/invoices/invoice_1001.txt
```

Prints only the result JSON to stdout; the mode banner, the one-time `Initialized ... and seeded inventory` notice, and a one-line summary go to stderr. A missing or empty `inventory.db` is created and seeded automatically. Exit codes: 0 processed, 1 the run failed, 2 usage error (bad file, bad date, live mode unavailable).

```bash
python main.py --invoice_path=data/invoices/invoice_1001.txt | python -m json.tool
python main.py --invoice_path=data/invoices/invoice_1001.txt --mode=offline --db=demo.db --output=result.json
```

Options: `--mode {offline,live}` (live needs `XAI_API_KEY` and `XAI_MODEL`; see below), `--retry RUN_ID` (see below), `--db`, `--output`, `--events` (default `output/events.jsonl`), `--evaluation-date YYYY-MM-DD` (default today). `main.py` adds `src/` to `sys.path`, so it works without the editable install.

## Retry a failed run

A live run that fails on a model error (`model_unavailable`, `model_timeout`, ...) ends `failed` with `recoverable: true`, the message "Model request failed. Payment was not attempted." and `next_actions` `retry` / `run offline as a separate simulation`. Retry it with the same file:

```bash
python main.py --retry RUN_ID --invoice_path=data/invoices/invoice_1001.txt
```

The retry is a new run linked by `retry_of`, in the original run's mode (`--mode` is ignored). It prints `Retrying run <id> (failed: <code>)`, then the normal summary. Refused with exit 2 and a reason: `not_failed`, `not_recoverable` (only model errors, `interrupted` and `unexpected_error` are retryable), `source_mismatch` (the file's SHA-256 differs from the original source; the ledger keeps no source bytes), `already_paid` (any other run that did not fail, including an earlier retry of the same run, already paid this invoice version; the existing receipt id is printed) or `unknown_run`. A run that ended `unexpected_error` reports `recoverable: true` with `next_actions` `retry` only. A retry still sees revisions after payment and version conflicts; a retry of a run that crashed before reaching an identity cannot be refused up front, so when another run has paid the same version it ends `duplicate` with that receipt, and an invoice is paid at most once: when the run that paid crashed afterwards, a same-mode replay or retry gets the existing receipt and the payment is re-attributed to it (`payment_run_repointed` audit event); a replay in the other mode gets the receipt without taking over the payment.

Running the same file in the other mode (for example `--mode offline` after a failed live run) is a separate, labeled run: when the latest run of that file was in the other mode, `runs.mode_switch_of` points at it (a further run in the same mode is not a switch). It skips the byte-level duplicate check and its agents never see the earlier run's recommendation or decision, but the identity check still counts the earlier run's outcome whatever its mode: a payment, or a business outcome of the same invoice version (for example offline `rejected`, then live), makes the switched run a `duplicate` of that run; another version's outcome is a version conflict. No code path turns a live failure into an offline result.

## Live mode configuration

Live mode reads `XAI_API_KEY`, `XAI_MODEL` (no default), `XAI_TIMEOUT_SECONDS` (default 30) and `MODEL_CALL_BUDGET` (default 6) from the environment, falling back to a git-ignored `.env` (copy `.env.example`; real variables win). Missing or invalid settings exit 2 before any run is created, naming the variable but never its value. `python -m invoice_processing.readiness [--ping]` reports the setup (exit 0 ready, 2 not); `--ping` makes one minimal SDK call and is the only path that touches the network. LangSmith tracing is forced off in both modes. Tests block `connect`, `connect_ex`, `create_connection` and `getaddrinfo`.

### Verify against real Grok (opt-in)

Default `uv run pytest` never touches the network: the live path is covered by a scripted fake client (`tests/test_live_contract.py`: every `ModelErrorCode`, tool authorization, and offline parity for all 20 samples). The real-API smoke test is skipped unless you ask for it:

```bash
# 1. Set a spending limit in the xAI console first (USD 10 is recommended for the first run).
# 2. XAI_API_KEY and XAI_MODEL in the environment or .env (no default model); check:
python -m invoice_processing.readiness --ping
# 3. Optional, for a cost estimate in the record (USD per million tokens, xAI pricing page):
export XAI_PRICE_INPUT_PER_MTOK=... XAI_PRICE_OUTPUT_PER_MTOK=...
RUN_LIVE_TESTS=1 uv run pytest -m live
```

It runs 11 invoices on fresh databases (INV-1001, 1002, 1003, 1012, 1013, 1014, the USD 10,000.01 fixture and the four adversarial fixtures) plus one invalid-key run, asserts business invariants only, and writes `docs/verification/live-<date>.md` (model id, SDK version, calls, latency, tool calls, tokens, cost estimate, divergences; never keys or prompts). Expect up to 6 model steps per invoice, so roughly 60 requests in total. Commit the record after reading it.

## Run every sample

```bash
for f in data/invoices/*; do python main.py --invoice_path="$f" --db=/tmp/demo.db; done
```

Use a fresh database (delete `/tmp/demo.db` first) to see the per-file outcomes: the corpus contains alternate formats and revisions of the same invoice, so later files in a shared database are reported as duplicates or revision conflicts.

## Seed the inventory

```bash
uv run python -m invoice_processing.seed --db inventory.db
```

Creates the database and schema if needed and inserts the required items (WidgetA 15, WidgetB 10, GadgetX 5, FakeItem 0). Re-running is safe: existing rows are never overwritten, and a stock value that differs from the seed is reported as a `WARNING` line and left as is.

An `inventory.db` from an earlier phase (schema version 3 or 4) is refused: delete it and re-seed. Phase 2 changed invoice identity keys (4); Phase 3 adds `runs.mode_switch_of` (5).

`--fresh` only creates a new database: it exits with code 2 and leaves the file untouched if the path already exists. Use it for repeatable demo databases.

## Lint and format

```bash
uv run ruff check .
uv run ruff format .
```

Ruff covers `src/` and `tests/`; `README.md` (the original assignment), `docs/`, and the provided `data/` fixtures are excluded.

## Regenerate the lock files

```bash
uv lock && uv export --format requirements-txt --no-hashes > requirements.lock
```

`uv.lock` is the source of truth; `requirements.lock` is an export for pip-only environments.

## Install without uv

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.lock
```

`requirements.lock` already contains `-e .` and the dev tools (pytest, ruff), so this installs everything.

## Verified on

Python 3.12.14, uv 0.12.5, macOS 25.6.0 (2026-11-01). Update when re-verified.

## Troubleshooting

**`ModuleNotFoundError: No module named 'invoice_processing'` on macOS.** This happens when the files in `.venv/` have the macOS `hidden` flag set (seen when the repo lives in an iCloud-synced Desktop or Documents folder). Python 3.12.10 and later skip hidden `.pth` files, so the editable install silently drops off `sys.path`. Fix with `chflags -R nohidden .venv`, or keep the repo outside iCloud-synced folders. Pytest is unaffected because `pyproject.toml` sets `pythonpath = ["src", "."]`.
