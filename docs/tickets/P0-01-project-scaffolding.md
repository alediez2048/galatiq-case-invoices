# P0-01 — Project scaffolding and tooling

Phase: 0 · Status: todo · Depends on: — · Requirements: A10 (reproducible install)

## Context

Nothing is installed yet. The [technology stack](../techstack.md) selects Python 3.12, `venv` + `pip`, `pyproject.toml`, Pytest, and Ruff, and asks that the locking workflow be chosen during scaffolding. Only dependencies used by the first working slice should be added.

## Scope

- `pyproject.toml` for package `invoice_processing` under `src/` (layout per [techstack — proposed repository layout](../techstack.md#proposed-repository-layout)), `requires-python = ">=3.12"`.
- Runtime dependency for this phase: `pydantic`. Dev dependencies: `pytest`, `ruff`.
- Choose and document the lock workflow (e.g. `pip-tools` → `requirements.lock` / `requirements-dev.lock`, or another tool); commit the lock files.
- Empty package skeleton: `src/invoice_processing/__init__.py`, `tests/` with a trivial passing test.
- Ruff config with a small documented rule set; Pytest config (`testpaths`, `pythonpath`).
- `.gitignore`: `.venv/`, `*.db`, `*.db-journal`, `*.db-wal`, `*.db-shm`, `uploads/`, `output/`, `*.jsonl`, `.env`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `node_modules/`.
- Short "Development setup" section in a new `docs/development.md` (create venv, install from lock, run tests, run lint). Do not modify the assignment `README.md` yet.

## Out of scope

`main.py`, LangGraph, FastAPI, xAI SDK, pdfplumber, defusedxml, frontend tooling. These arrive with the phases that use them.

## Acceptance criteria

- [ ] From a fresh clone: `python3.12 -m venv .venv`, install from the lock, `pytest` and `ruff check .` and `ruff format --check .` all pass.
- [ ] Lock workflow and its regenerate command are documented in `docs/development.md`.
- [ ] `git status` is clean after running tests and creating a database file in the repo root.
- [ ] Python version and OS used for verification are recorded in `docs/development.md`.
