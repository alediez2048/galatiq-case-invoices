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

## Seed the inventory

```bash
uv run python -m invoice_processing.seed --db inventory.db
```

Creates the database and schema if needed and inserts the required items (WidgetA 15, WidgetB 10, GadgetX 5, FakeItem 0). Re-running is safe: existing rows are never overwritten, and a stock value that differs from the seed is reported as a `WARNING` line and left as is.

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
