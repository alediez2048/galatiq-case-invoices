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
