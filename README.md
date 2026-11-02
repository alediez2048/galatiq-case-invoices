# Invoice processing agents: Galatiq case solution

This repository is a solution to the Galatiq invoice-processing case. The assignment text is kept unchanged under [Original assignment](#original-assignment) at the end of this file.

## What it does

A local command-line prototype takes one invoice file (TXT, JSON, CSV, XML or text PDF), extracts vendor, items, quantities, amounts and due date, and records every normalization with its source evidence. It checks the invoice against a SQLite inventory and its own arithmetic. An approval agent then makes a recommendation, critiques it and may revise it once, and a deterministic gate gives the final decision. Clean USD invoices up to USD 10,000.00 are paid through a guarded mock payment that pays each invoice identity at most once, including across reruns, file formats and revisions. Everything else ends `rejected`, `needs_review` or `awaiting_human_approval`, with stable reason codes. The workflow is a four-agent LangGraph graph over one shared processing service. It runs in **offline** mode by default, where a labeled deterministic simulator stands in for the model, or in **live** mode, where xAI Grok does the reasoning (needs your own API key).

<!-- TODO(P6-04): add a UI screenshot here once the React UI (Phase 5) exists. -->

## Quick start

<!-- TODO(P6-04): replace <repository-url> with the public GitHub URL once published (P6-06). -->

Prerequisites: Python 3.12 and [uv](https://docs.astral.sh/uv/) (verified with uv 0.12.5 on macOS). No API key or network access is needed after installation.

```bash
git clone <repository-url> && cd <repository-directory>
uv sync --locked                                     # install exactly what uv.lock pins
uv run python -m invoice_processing.seed --db inventory.db   # create and seed the inventory
uv run python main.py --invoice_path=data/invoices/invoice_1001.txt
```

The last command prints the result JSON to stdout (`"status": "paid_mock"`, a USD 5,000.00 mock receipt) and the mode banner and a one-line summary to stderr. If `inventory.db` is missing, `main.py` creates and seeds it on its own. Running the same file again returns `duplicate` with the same receipt and no second payment. Without uv: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.lock`, then use `.venv/bin/python` in place of `uv run python`.

Run all 20 samples, each on its own fresh database, as the results table below does:

```bash
for f in data/invoices/*; do
  printf '%-28s ' "$(basename "$f")"
  uv run python main.py --invoice_path="$f" --db="$(mktemp -d)/demo.db" \
    --evaluation-date=2026-01-31 --output=/dev/null 2>&1 | grep '^status='
done
```

Run all 20 through one shared ledger, to see duplicate and revision protection (7 payments, no identity paid twice):

```bash
db="$(mktemp -d)/shared.db"
for f in data/invoices/*; do uv run python main.py --invoice_path="$f" --db="$db" --output=/dev/null; done
```

Run the tests and lint:

```bash
uv run pytest                 # 2026-11-01: 725 passed, 1 xfailed (a recorded bug); no network, no credentials
uv run ruff check . && uv run ruff format --check .
```

CLI options: `--mode {offline,live}` (default `offline`), `--db`, `--output`, `--events` (JSON-lines log, default `output/events.jsonl`), `--evaluation-date YYYY-MM-DD`. Exit codes: 0 processed, 1 run failed, 2 usage error. More detail is in [docs/development.md](docs/development.md).

### API and UI

```bash
(cd frontend && npm ci && npm run build)            # Node 22 or newer (frontend/package.json engines)
uv run python -m invoice_processing.api            # http://127.0.0.1:8000, API docs at /docs
```

The API binds to `127.0.0.1` only and serves the built UI from `frontend/dist` at `/`. For UI development, run the API as above and `npm run dev` in `frontend/` (http://127.0.0.1:5173, proxies `/api`). Browser end-to-end tests (Playwright) run with `cd frontend && npm run test:e2e`, which builds first. See [docs/development.md](docs/development.md#frontend).

### Live smoke test (optional, paid)

```bash
RUN_LIVE_TESTS=1 uv run pytest -m live
```

This makes real, paid calls to xAI (about 11 invoices, up to 6 model steps each, so roughly 60 requests) and needs `XAI_API_KEY` and `XAI_MODEL`. Set a spending limit in the xAI console first; USD 10 is a sensible cap for a first run. Without `RUN_LIVE_TESTS=1` the test is skipped, and the default `uv run pytest` never touches the network. See [Offline and live modes](#offline-and-live-modes).

## Offline and live modes

The brief asks for Grok as the reasoning engine and also says to assume no internet. A single run cannot do both, so the prototype has two explicitly selected modes ([decision](docs/decisions.md#d-dual-mode), [limitation](docs/limitations.md#l-offline-vs-llm)):

| | Offline (default) | Live |
| --- | --- | --- |
| Reasoning | Deterministic simulator, every summary labeled `offline simulation:` | Grok through the official `xai_sdk`, model named by `XAI_MODEL` |
| Network | None; tests block sockets | Model calls only (invoice text is sent to xAI); inventory and payment stay local and mock |
| Selected by | omitting `--mode`, or `--mode offline` | `--mode live` plus credentials |

Both modes share the parsers, validation, gate and payment guard, so a mode never changes business rules: the model recommends and critiques, the deterministic gate decides. The offline simulator is not a model. It shows that the agent flow and safety rules work, not that an LLM reasons well.

### Running live

Live mode needs `XAI_API_KEY` and `XAI_MODEL` (no default model). Set them in the environment or copy `.env.example` to a git-ignored `.env` (real environment variables win; offline mode never loads `.env`). Optional: `XAI_TIMEOUT_SECONDS` (default 30) and `MODEL_CALL_BUDGET` (default 6 model steps per invoice).

```bash
uv run python -m invoice_processing.readiness          # config only, no network; exit 0 ready, 2 not
uv run python -m invoice_processing.readiness --ping   # one minimal SDK call: the only check that uses the network
uv run python main.py --mode live --invoice_path=data/invoices/invoice_1001.txt
```

- **Without credentials** (or with an invalid setting) `--mode live` exits 2 before any run is created, naming the missing variable but never its value. Nothing falls back to offline.
- **Budget.** Each invoice may use at most `MODEL_CALL_BUDGET` model steps (recommend, critique, at most one revision, plus bounded tool turns). Exhausting it ends the run as a model error instead of sending more requests.
- **Model failure.** If the model errors or times out, the run ends `failed` with `recoverable: true`, "Payment was not attempted", and next actions `retry` / `run offline as a separate simulation`. Retry with `uv run python main.py --retry RUN_ID --invoice_path=<same file>`; the retry is a new linked run in the original mode. The same actions are buttons in the UI.
- **Mode switch.** Running a file in the other mode is a separate, labeled run (`mode_switch_of`). It never reuses the earlier run's recommendation, and no code path turns a live failure into an offline result. An invoice is still paid at most once across modes.
- **Privacy.** The key is never printed, logged or stored; LangSmith tracing is forced off in both modes.

Developer details (retry refusal reasons, test coverage of the live path) are in [docs/development.md](docs/development.md#live-mode-configuration).

<!-- TODO(P6-04): add live verification results (model id, SDK version, per-invoice status, calls, tokens, cost) from docs/verification/live-<date>.md once P3-10 runs. -->

## Architecture

```
intake → parsers → normalization → identity / duplicate check → validation
       → approval agent (recommend → critique → ≤1 revision) → deterministic gate → guarded mock payment
```

- Four LangGraph agents: ingestion, validation, approval, payment ([`workflow.py`](src/invoice_processing/workflow.py)). The CLI and the planned API call the same service ([`service.py`](src/invoice_processing/service.py)).
- Deterministic code owns arithmetic, inventory, eligibility and payment. The model's recommendation is one input to the gate ([`policy.py`](src/invoice_processing/policy.py)) and can never authorize a payment by itself.
- One SQLite file holds inventory, sources, invoices and versions, runs, findings, decisions, payments (unique per invoice identity) and audit events.

The full picture, with a Mermaid diagram, the ledger tables, the planned tool whitelist and the safety invariants, is in [docs/architecture.md](docs/architecture.md).

## Results on the 20 supplied files

Offline mode, each file on a freshly seeded database, evaluation date 2026-01-31. Asserted by [`tests/test_acceptance.py`](tests/test_acceptance.py) (`CASES` and `test_fixture_outcome`) and reproduced with the loop in the quick start.

| File | Status | Paid (USD) | Key reasons |
| --- | --- | --- | --- |
| `invoice_1001.txt` | `paid_mock` | 5,000.00 | Clean; no currency stated, so `currency_assumed_usd` is recorded |
| `invoice_1002.txt` | `rejected` | — | `quantity_exceeds_stock` (GadgetX 20 > 5); misspelled labels normalized; `terms_inconsistent` |
| `invoice_1003.txt` | `rejected` | — | `zero_stock` (FakeItem), `due_date_unresolved` ("yesterday"); urgent wording is only a `risk_signal_urgency` |
| `invoice_1004.json` | `paid_mock` | 1,890.00 | Clean |
| `invoice_1004_revised.json` | `paid_mock` | 5,940.00 | Clean on its own; on a shared ledger after 1004 it is `needs_review` (`revision_after_payment`) |
| `invoice_1005.json` | `rejected` | — | `quantity_exceeds_stock` (GadgetX 8 > 5) |
| `invoice_1006.csv` | `paid_mock` | 2,750.00 | Clean; `currency_assumed_usd` |
| `invoice_1007.csv` | `rejected` | — | `quantity_exceeds_stock` (WidgetA 20 > 15, WidgetB 15 > 10), `total_mismatch` (stated 15,525.00, computed 15,635.00) |
| `invoice_1008.txt` | `rejected` | — | `unknown_item` (SuperGizmo, MegaSprocket) |
| `invoice_1009.json` | `rejected` | — | `missing_vendor`, `missing_due_date`, `non_positive_quantity`, `non_positive_total`, `subtotal_mismatch` |
| `invoice_1010.txt` | `paid_mock` | 7,185.00 | "(rush order)" alias resolved to WidgetA; repeated lines aggregated to 12 |
| `invoice_1011.txt` | `paid_mock` | 3,000.00 | Clean |
| `invoice_1011.pdf` | `paid_mock` | 3,000.00 | Clean; on a shared ledger it is a `duplicate` of the TXT with the same receipt |
| `invoice_1012.txt` | `paid_mock` | 9,975.00 | OCR-style fixes applied with recorded evidence (spaced item names, `2O26`, `3,500.O0`) |
| `invoice_1012.pdf` | `paid_mock` | 9,975.00 | Same fixes; on a shared ledger a `duplicate` of the TXT |
| `invoice_1013.json` | `rejected` | — | `quantity_exceeds_stock` after aggregation (WidgetA 22, WidgetB 18, GadgetX 9), `total_mismatch` (22,562.80 vs 22,512.80) |
| `invoice_1013.pdf` | `rejected` | — | Same as the JSON; on a shared ledger a `duplicate` with no receipt |
| `invoice_1014.xml` | `needs_review` | — | EUR 4,125 kept as EUR, never converted: `unsupported_currency`, `non_usd_currency` |
| `invoice_1015.csv` | `paid_mock` | 6,500.00 | Clean; `currency_assumed_usd` |
| `invoice_1016.json` | `rejected` | — | `unknown_item` (WidgetC) |

Per file, 10 are paid, 9 rejected and 1 held for review. Through one shared ledger the 20 files are 16 invoice identities, and exactly 7 are paid (1001, 1004, 1006, 1010, 1011, 1012, 1015). Neither format twins nor the 1004 revision pay a second time ([`test_shared_ledger_never_pays_an_identity_twice`](tests/test_acceptance.py), and in both processing orders in [`tests/test_robustness_corpus.py`](tests/test_robustness_corpus.py)). None of the supplied invoices is both clean and over USD 10,000, so the high-value hold is shown with the threshold fixtures in [`tests/fixtures/robustness/`](tests/fixtures/robustness/): 10,000.00 pays and 10,000.01 waits in `awaiting_human_approval` ([`tests/test_robustness_threshold.py`](tests/test_robustness_threshold.py)).

## How the evaluation criteria are addressed

| Criterion | What is there now | Evidence |
| --- | --- | --- |
| Functionality | End to end from file to mock receipt or a reasoned rejection, for all 20 samples and five formats | [`tests/test_acceptance.py`](tests/test_acceptance.py), [`tests/test_e2e.py`](tests/test_e2e.py) (CLI subprocess runs) |
| Code quality | Typed Pydantic contracts, decimal money, stable finding and error codes, JSON-lines events and audit rows, ruff clean. 725 tests, including error injection at every stage, 37 malformed inputs, replayed CLI runs and threshold boundaries; the one bug found is recorded as a strict xfail | [`schemas.py`](src/invoice_processing/schemas.py), [`codes.py`](src/invoice_processing/codes.py), [`tests/test_observability.py`](tests/test_observability.py), [`tests/test_e2e.py::test_e2e_audit_trail`](tests/test_e2e.py), [robustness record](docs/verification/robustness-2026-11-01.md) |
| Agentic sophistication | Four LangGraph agents; recommend → critique → at most one revision; structured outputs; a reasoning-provider interface ready for Grok. On `main` the reasoning is the offline simulator, and tool calls and live Grok are in progress | [`agents/approval.py`](src/invoice_processing/agents/approval.py), [`tests/test_agents.py::test_approval_one_critique_at_most_one_revision`](tests/test_agents.py), [`tests/test_workflow.py`](tests/test_workflow.py), [Phase 3 plan](docs/superpowers/plans/2026-11-01-phase-3-live-grok.md) |
| Shipping mindset | Walking skeleton first, then the full corpus; a written cut line; open questions resolved or disclosed | [Tickets and cut line](docs/tickets/README.md), [decisions](docs/decisions.md), [limitations](docs/limitations.md) |
| Presentation | Business impact below, tied to the brief's pain points, with illustrative numbers labeled | [Business impact](#business-impact) |
| Above and beyond | Duplicate and revision protection across formats; hardened XML; OCR-style fixes with provenance; EUR never converted; past-payment revisions held; data finding on INV-1007's stated total | [`tests/test_payments.py`](tests/test_payments.py), [`tests/test_parser_xml.py`](tests/test_parser_xml.py), [`tests/test_normalize.py`](tests/test_normalize.py), [decision on INV-1007](docs/decisions.md#d-inv1007) |
| UI/UX | Planned (Phase 5): React + TypeScript on FastAPI. Today there is a static visual mockup and a CLI whose stdout is clean JSON and whose stderr gives a readable summary | [Mockup spec](docs/mockup.md), [`docs/mockups/index.html`](docs/mockups/index.html), [style guide](docs/styleguide.md) |

## Business impact

The brief's figures (USD 2M a year, 30% error rate, five-day delay) are scenario inputs. This prototype has not been measured against real invoice volume, and nothing below is a promised saving.

| Pain point | Design choice | What the repo shows |
| --- | --- | --- |
| 30% error rate | Deterministic checks for every rule that can be checked by code: required fields, signs, decimal arithmetic to the cent, aggregated stock, unknown items, duplicates. Each finding carries a code, expected and observed values, and source evidence. | Each of the 10 sample files that should not auto-pay is stopped with specific codes, and the checks found a 110.00 total error in INV-1007 that the first hand analysis of the samples missed ([results](#results-on-the-20-supplied-files), [`tests/test_acceptance.py`](tests/test_acceptance.py)) |
| Five-day delay | Clean USD invoices up to USD 10,000.00 are approved and paid automatically, with no human step | 10 of 20 sample files (7 of 16 identities) pay without a person; a local run of INV-1001 spent a few milliseconds per stage (`timings_ms` in the result JSON) |
| VP approval by email chain | Invoices over USD 10,000 wait in `awaiting_human_approval` after the agent's recommendation and critique, and a human approval is bound to the exact invoice version | The hold is built and tested ([`tests/test_robustness_threshold.py`](tests/test_robustness_threshold.py)). The approval queue and approve/decline actions are **planned (Phase 4)**, with a UI in Phase 5 |

**Illustrative only.** Assume (a) 30% of invoices have an error, as the brief says, (b) the checks here catch the same kinds of errors as in the samples, and (c) the share of clean invoices up to USD 10,000 matches the samples, about 7 of 16. Under those assumptions roughly 4 in 10 invoices would need no manual handling, and errored invoices would be stopped before payment with a stated reason instead of being found later. These assumptions are unverified: real error types, invoice values and vendor mix will differ, and the prototype has no PO matching, vendor master or price checks that a production deployment would need.

## Assumptions and limitations

The full list, with consequences, is in [docs/limitations.md](docs/limitations.md). In short:

- Payment is a mock. Idempotency is enforced locally, but a real bank API would also need to dedupe on the key ([robustness record](docs/verification/robustness-2026-11-01.md)).
- No purchase orders, vendor master or price list. Validation is limited to inventory, arithmetic and required fields.
- No OCR. PDFs must have a text layer; the three supplied PDFs do.
- Settlement is USD only. EUR and other currencies go to review and are never converted ([limitation](docs/limitations.md#l-eur)).
- Inventory is checked, not reserved or decremented, so two invoices can each fit the same stock ([limitation](docs/limitations.md#l-revisions)).
- One local operator, no authentication, processing serialized.
- The offline simulator is not a model. Live Grok has not been run against the real provider yet ([limitation](docs/limitations.md#l-live-credentials)).
- Verified on the developer's macOS machine only.

Project documents: [PRD](docs/PRD.md), [requirements](docs/requirements.md), [system design](docs/systemsdesign.md), [architecture](docs/architecture.md), [decisions](docs/decisions.md), [limitations](docs/limitations.md), [development](docs/development.md), [tickets](docs/tickets/README.md).

## Original assignment

The text below is the assignment README exactly as received (commit `3452e95`). It is not edited. To check: `diff <(sed '1,/^<!-- ORIGINAL ASSIGNMENT BELOW/d' README.md) <(git show 3452e95:README.md)` prints nothing.

<!-- ORIGINAL ASSIGNMENT BELOW: verbatim copy of README.md at commit 3452e95. Do not edit anything after this line. -->
# Galatiq Case: Invoice Processing Automation

## Background

Acme Corp is a PE-backed manufacturing firm losing **$2M/year** on manual invoice processing. Invoices arrive via email as PDFs in messy formats with frequent errors. Staff manually extract data, validate against a legacy inventory database (inconsistent), obtain VP approval (via email chains), and process payment (via a banking API).

**Current pain points:**
- 30% error rate
- 5-day processing delays
- Frustrated stakeholders

## Objective

Build a **multi-agent system** that automates the end-to-end invoice processing workflow. The system must run as a working prototype — not just designs or slides.

## Workflow

The system should handle four stages:

1. **Ingestion** — Extract structured data from invoice documents (PDFs, text files). Fields include: Vendor, Amount, Items (with quantities), and Due Date. Expect unstructured text, typos, missing data, and potentially fraudulent entries.

2. **Validation** — Verify extracted data against a mock inventory database (SQLite). Flag mismatches such as quantity exceeding available stock or items not found in inventory.

3. **Approval** — Simulate VP-level review with rule-based decision-making (e.g., invoices over $10K require additional scrutiny). The agent should reason through approval/rejection with a reflection or critique loop.

4. **Payment** — If approved, call a mock payment function. If rejected, log the rejection with reasoning.

## Technical Requirements

- **LLM Integration**: Use xAI's Grok as the core reasoning engine (via the xAI API at https://grok.x.ai). Other models are acceptable if you don't have an API key.
- **Multi-Agent Orchestration**: Use a framework such as LangGraph, CrewAI, AutoGen, or a custom solution.
- **Agent Capabilities**: Function calling / tool use, structured outputs, and self-correction loops.
- **Runtime**: Assume no internet for external APIs — simulate everything locally.
- **Tech Stack**: Python (preferred), with libraries like `langchain`, `crewai`, `autogen`, `pdfplumber`, `PyMuPDF`, etc. Run locally — no cloud deployment.

## Provided Resources

### Mock Invoice Data

Sample invoices are provided in the `data/invoices/` directory in various formats (PDF, CSV, JSON, TXT). Use these as inputs for testing. The data intentionally includes a mix of clean entries and problematic ones — identifying and handling issues is part of the challenge.

### Mock Inventory Database (Required Setup)

Before running the system, you **must** create a local SQLite database that the validation agent will check invoices against. The sample invoices in `data/invoices/` reference specific items and quantities — your database needs to contain matching inventory records so the validation stage can flag mismatches, out-of-stock items, and unknown products.

Below is a starter schema and seed data that covers the core items referenced across the provided invoices:

```python
import sqlite3

conn = sqlite3.connect('inventory.db')  # Persist to file so all agents can access it
cursor = conn.cursor()

cursor.execute('CREATE TABLE IF NOT EXISTS inventory (item TEXT PRIMARY KEY, stock INTEGER)')
cursor.execute("""
    INSERT INTO inventory VALUES
    ('WidgetA', 15),
    ('WidgetB', 10),
    ('GadgetX', 5),
    ('FakeItem', 0)
""")
conn.commit()
```

**Why this matters:** The sample invoices are designed to test your validation logic against this database. For example:

| Scenario | Invoice | What should happen |
|---|---|---|
| Normal order within stock | INV-1001, INV-1004, INV-1006 | Items found, quantities valid — passes validation |
| Quantity exceeds stock | INV-1002 (requests 20× GadgetX, only 5 in stock) | Flagged as stock mismatch |
| Fraudulent / zero-stock item | INV-1003 (references FakeItem, 0 stock) | Flagged as out of stock or suspicious |
| Item not in database at all | INV-1008 (SuperGizmo, MegaSprocket), INV-1016 (WidgetC) | Flagged as unknown item |
| Invalid data | INV-1009 (negative quantity) | Flagged as data integrity issue |

You may extend the seed data with additional items or columns (e.g., unit price, category) to support richer validation — the above is the minimum needed to exercise the provided test invoices. If you want your system to also validate pricing or vendor information, consider adding tables for those as well.

### Mock Payment API

```python
def mock_payment(vendor, amount):
    print(f"Paid {amount} to {vendor}")
    return {"status": "success"}
```

### Grok API Setup

```python
from xai import Grok

client = Grok(api_key="your_key")
response = client.chat.completions.create(
    model="grok-3",
    messages=[{"role": "user", "content": "Reason about this..."}]
)
```

## Running the System

The system should be executable from the command line:

```bash
python main.py --invoice_path=data/invoices/invoice1.txt
```

Output should include structured logs and results.

## Evaluation Criteria

- **Functionality** — Does the system work end-to-end?
- **Code Quality** — Clean, testable, well-structured code with error handling and observability
- **Agentic Sophistication** — LLM integration, multi-agent flow, tool use, self-correction loops
- **Shipping Mindset** — Valuable MVP delivered under ambiguity; scope ruthlessly cut where needed
- **Presentation** — Clear translation of technical decisions to business impact
- **Above/Beyond** - Have you made it your own? Implemented additional features that make the solution feel great? Expanded assumptions? Added to test cases?
- **UI/UX** - Users will understand and enjoy using this system.

## Submission

Submit your solution as a link to a public GitHub repository — GitHub only (github.com).
