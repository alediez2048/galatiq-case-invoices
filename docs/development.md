# Development

## Prerequisites

- Python 3.12, managed by [uv](https://docs.astral.sh/uv/) (`.python-version` pins 3.12).
- Node.js 22 and npm 10 for the Phase 5 frontend (`frontend/`).

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

Options: `--mode {offline,live}` (live is unavailable until Phase 3), `--db`, `--output`, `--events` (default `output/events.jsonl`), `--evaluation-date YYYY-MM-DD` (default today). `main.py` adds `src/` to `sys.path`, so it works without the editable install.

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

A Phase 1 `inventory.db` (schema version 3) is refused: delete it and re-seed, because invoice identity keys changed in Phase 2.

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

## Frontend

React + TypeScript (strict) with Vite, in `frontend/`. `package-lock.json` is committed; use `npm ci`.

```bash
cd frontend
npm ci
npm run dev        # http://127.0.0.1:5173, proxies /api to FastAPI on 127.0.0.1:8000 (API_PORT overrides)
npm run typecheck
npm run lint
npm test           # Vitest + Testing Library, fixture data only
npm run build      # dist/, then checks the bundle references no external origin and no test fixtures
```

`VITE_MOCK_API=1 npm run dev` serves the UI against the test fixtures without a backend (dev server only; `import.meta.env.DEV` removes it from builds, and `npm run build` fails if fixture data leaks into `dist/`).

The API types in `frontend/src/api/types.ts` are hand-written from the P5-02/P5-03 tickets and `schemas.py`; replace them with `openapi-typescript` output from `frontend/src/api/openapi.json` once the backend exports it. No fonts, CDNs or analytics are loaded at runtime; the font stack is `Aventa, Arial, sans-serif` with no bundled Aventa.
