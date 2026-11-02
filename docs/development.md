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

Options: `--mode {offline,live}` (live needs `XAI_API_KEY` and `XAI_MODEL`; see below), `--retry RUN_ID` (see below), `--db`, `--output`, `--events` (default `output/events.jsonl`), `--evaluation-date YYYY-MM-DD` (default today). `main.py` adds `src/` to `sys.path`, so it works without the editable install.

## Retry a failed run

A live run that fails on a model error (`model_unavailable`, `model_timeout`, ...) ends `failed` with `recoverable: true`, the message "Model request failed. Payment was not attempted." and `next_actions` `retry` / `run offline as a separate simulation`. Retry it with the same file:

```bash
python main.py --retry RUN_ID --invoice_path=data/invoices/invoice_1001.txt
```

The retry is a new run linked by `retry_of`, in the original run's mode (`--mode` is ignored). It prints `Retrying run <id> (failed: <code>)`, then the normal summary. Refused with exit 2 and a reason: `not_failed`, `not_recoverable` (only model errors, `interrupted` and `unexpected_error` are retryable), `source_mismatch` (the file's SHA-256 differs from the original source; the ledger keeps no source bytes), `already_paid` (any other run that did not fail, including an earlier retry of the same run, already paid this invoice version; the existing receipt id is printed) or `unknown_run`. A run that ended `unexpected_error` reports `recoverable: true` with `next_actions` `retry` only. A retry still sees revisions after payment and version conflicts; a retry of a run that crashed before reaching an identity cannot be refused up front, so when another run has paid the same version it ends `duplicate` with that receipt, and an invoice is paid at most once: when the run that paid crashed afterwards, a same-mode replay or retry gets the existing receipt and the payment is re-attributed to it (`payment_run_repointed` audit event); a replay in the other mode gets the receipt without taking over the payment.

Running the same file in the other mode (for example `--mode offline` after a failed live run) is a separate, labeled run: when the latest run of that file was in the other mode, `runs.mode_switch_of` points at it (a further run in the same mode is not a switch). It skips the byte-level duplicate check and its agents never see the earlier run's recommendation or decision, but the identity check still counts the earlier run's outcome whatever its mode: a payment, or a business outcome of the same invoice version (for example offline `rejected`, then live), makes the switched run a `duplicate` of that run; another version's outcome is a version conflict. No code path turns a live failure into an offline result.

## Review workflow

Phase 4 adds the human review actions as Python calls in `invoice_processing.review` (there is no review CLI; P4-06 is deferred). Each action checks the version the reviewer saw, records an immutable row and a new run in one transaction, then runs that run with no transaction open and returns a `ProcessingResult`. Refusals raise `review.ReviewRefused` with a stable `code` (`ReviewRefusal`), a `message` and `current` (the invoice's `AllowedActions`: status, current version, allowed and refused actions). A blank reviewer or reason (1–100 and 1–1,000 characters after stripping) raises Pydantic `ValidationError` before the database is opened. The reviewer is a free-text name kept for audit, not authentication.

```python
from datetime import date
from invoice_processing import review
from invoice_processing.schemas import CorrectionRequest, FieldChange

db = "demo.db"

# Invoices waiting on a person: groups correctable_extraction, awaiting_human_approval,
# unresolved_blocker; each item has reason codes, current version and allowed actions.
queue = review.list_queue(db_path=db)
actions = review.allowed_actions(invoice_id, db_path=db)

# Fix an extraction mistake, citing where the source states the value.
result = review.submit_correction(
    CorrectionRequest(
        invoice_id=invoice_id,
        expected_version=1,
        changes=[FieldChange(field="stated.total", new_value="3500.00", evidence_location="line:13")],
        reason="Total misread",
        reviewer="Ana",
    ),
    db_path=db,
)

# Approve or decline the waiting version (over USD 10,000, or after a model disagreement).
result = review.approve(invoice_id, 2, "Ana", "Checked against PO", db_path=db)
result = review.decline(invoice_id, 2, "Ana", "Vendor not on contract", db_path=db)

# A corrected invoice from the vendor supersedes the unpaid versions of the same invoice.
result = review.submit_corrected_invoice(
    invoice_id, "corrected.json", "Vendor reissued", "Ana",
    db_path=db, evaluation_date=date(2026, 1, 31),
)
```

- **Corrections** (`submit_correction`): up to 10 field changes, all or nothing. Field paths are `vendor`, `invoice_number`, `invoice_date`, `due_date`, `currency`, `stated.subtotal|tax|shipping|total` and `lines[N].item|quantity|unit_price|line_total`. Each cited location must resolve in the stored source text, use the scheme the parser records for the format (TXT `line:N`, PDF `page:P,line:N`, CSV `row:N[,col:…]`, JSON `$…`, XML `/…`), and not be another field's location; the text there must support the new value. Otherwise the refusal is `evidence_location_mismatch` or `correction_not_in_source` ("This value is not what the invoice says. Submit a corrected invoice from the vendor."). Other codes: `stale_version`, `already_paid`, `invalid_value`, `field_not_correctable` (for example a stated EUR), `identity_correction_deferred` (a vendor or number change), `source_text_unavailable` / `evidence_unavailable` (invoices processed before Phase 4), `no_change` (a new value equal to the version's current value, checked last, so a no-op version cannot re-queue a declined invoice; restating a value is accepted only when it drops a carried review or blocker finding on that field, such as `model_parser_disagreement`). A correction creates version N+1, marks the old version `superseded`, records `approvals_invalidated`, and reruns validation, recommendation and critique from scratch in the base run's mode. A clean corrected invoice up to USD 10,000 pays without further action.
- **Approve / decline**: allowed only while the invoice is `awaiting_human_approval` and `expected_version` is current (otherwise `action_not_allowed` or `stale_version`). The review run revalidates against the current inventory and reaches the gate with the waiting run's recommendation; it never calls a model, so a live invoice needs no credentials to approve. Approval never clears a blocker or review finding. Decline rejects with `human_declined`. A repeated approve of the paid version returns the same receipt and writes nothing. EUR invoices are never payable.
- **Corrected submissions** (`submit_corrected_invoice`): allowed with no payment, status `rejected`, `needs_review` or `failed`, and no version awaiting approval, approved or paid. The file must carry the same vendor and invoice number (else the run fails `corrected_identity_mismatch`); a version that becomes held before the write fails the run with `supersede_not_allowed` (not retryable). Uploading the same file through `process_invoice` stays `version_conflict`.
- **Retries**: a failed correction or approve/decline run (for example a live model failure during re-review, or a run left `interrupted`) is retried on its own version without a file: `service.retry_run(run_id, None, db, evaluation_date)` or `python main.py --retry RUN_ID`. A retried approve/decline again calls no model. A retry whose version is no longer current is refused `not_current`.
- `submit_correction`, `approve`, `decline` and `submit_corrected_invoice` take an optional `on_run_started(run_id)` callback, called once the new run is committed and before it executes.

## Live mode configuration

Operator notes (environment variables, readiness check, `--ping`, call budget, behaviour without credentials, the paid smoke test) are in the README under [Offline and live modes](../README.md#offline-and-live-modes). Developer-only details:

Settings load from the environment, falling back to `./.env` (current directory only; `settings.load_dotenv_file` is the single place it is read and tests replace it). LangSmith tracing is forced off in both modes. Tests block `connect`, `connect_ex`, `create_connection` and `getaddrinfo`.

The default `uv run pytest` never touches the network: the live path is covered by a scripted fake client (`tests/test_live_contract.py`: every `ModelErrorCode`, tool authorization, and offline parity for all 20 samples). The real-API smoke test (`tests/live/test_live_smoke.py`) runs 11 invoices on fresh databases (INV-1001, 1002, 1003, 1012, 1013, 1014, the USD 10,000.01 fixture and the four adversarial fixtures) plus one invalid-key run, asserts business invariants only, and writes `docs/verification/live-<date>.md` (model id, SDK version, calls, latency, tool calls, tokens, cost estimate, divergences; never keys or prompts). Optional `XAI_PRICE_INPUT_PER_MTOK` and `XAI_PRICE_OUTPUT_PER_MTOK` (USD per million tokens) add a cost estimate. Commit the record after reading it.

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

Phase 4 uses schema version 7 (review tables, run triggers, immutability triggers) and upgrades a version 6 database in place. An `inventory.db` from anything older is refused: delete it and re-seed. Phase 2 changed invoice identity keys (4); Phase 3 adds `runs.mode_switch_of` (5).

`--fresh` only creates a new database: it exits with code 2 and leaves the file untouched if the path already exists. Use it for repeatable demo databases.

## Run the API

```bash
uv run python -m invoice_processing.api            # http://127.0.0.1:8000, docs at /docs
uv run python -m invoice_processing.api --db demo.db --port 8001
```

Binds to `127.0.0.1` only; any other host needs `--allow-public-bind` (there is no authentication). The database is created and seeded on startup (never reset); a database from an older schema version (anything below 6) is refused, so point `--db` at a new path. If `frontend/dist` exists it is served at `/`. Uploads are stored under `uploads/<sha256>/` (gitignored); processing runs in one background worker under a process-wide lock, and clients poll `GET /api/runs/{run_id}`.

`POST /api/runs/{run_id}/retry` retries a recoverable failed run as a new linked run (`service.retry_run`; body `{"action": "retry"}`, the default, keeps the run's mode) or, for a live model failure, `{"action": "run_offline"}` runs the same document offline as a separate simulation (`mode_switch_of`). It accepts an `Idempotency-Key` header and re-reads the original file (bundled sample or stored upload, located by hash). Refusals use the `RetryRefused` reason as the error code: `unknown_run` 404; `not_failed`, `not_recoverable`, `source_mismatch`, `already_paid` (with `details.receipt_id`) 409; plus `source_unavailable` 409 when the original file is gone and `provider_unavailable` 409 when live settings are missing. `GET /api/settings/readiness` reports live availability from configuration only (`readiness.live_status`, no SDK import or network) and the configured `live_model`.

Export the OpenAPI schema for the typed frontend client: `uv run python scripts/export_openapi.py` (writes `frontend/src/api/openapi.json`).

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
npm run test:e2e   # Playwright: builds into frontend/dist, then runs against e2e/serve.py
```

`npm run test:e2e` needs `npm ci` first (and `npx playwright install chromium` once per machine). It overwrites `frontend/dist` with a fresh build and serves it from a throwaway offline database in a temp directory (`e2e/serve.py`, on `127.0.0.1:18765`), so it never touches `inventory.db` or `data/invoices/`.

`VITE_MOCK_API=1 npm run dev` serves the UI against the test fixtures without a backend (dev server only; `import.meta.env.DEV` removes it from builds, and `npm run build` fails if fixture data leaks into `dist/`).

API types are generated, never hand-written. After changing a response model in `api.py` / `queries.py`:

```bash
uv run python scripts/export_openapi.py        # writes frontend/src/api/openapi.json
(cd frontend && npm run gen:api)               # writes frontend/src/api/schema.d.ts
uv run python scripts/export_ui_fixtures.py    # optional: refresh real-response test fixtures
```

`tests/test_api.py` fails if `openapi.json` is stale and `src/api/schema.test.ts` fails if `schema.d.ts` is stale. `frontend/src/api/adapters.ts` maps the wire types to the view models components render; it is the only file that knows both shapes. No fonts, CDNs or analytics are loaded at runtime; the font stack is `Aventa, Arial, sans-serif` with no bundled Aventa.
