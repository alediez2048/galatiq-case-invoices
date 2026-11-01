# Technology stack

Status: proposed choices for implementation, not installed dependencies. This is a Python-first local prototype. Package versions will be selected, tested together, and locked when the environment is created; no unverified “latest” pins are prescribed here.

Related: [requirements](requirements.md), [constraints](contraints.md), [system design](systemsdesign.md).

## Selected baseline

| Area | Proposed tool | Purpose and rationale |
| --- | --- | --- |
| Runtime | Python 3.12 | One language for parsing, agents, persistence, CLI, tests, and UI. Validate dependency compatibility before locking. |
| Environment | `venv`, `pip`, `pyproject.toml`, pinned dependency lock/requirements export | Conventional local setup and reproducible installs. Choose the concrete locking workflow during scaffolding. |
| Orchestration | LangGraph | Explicit graph state, conditional routing, bounded repair/critique paths, and distinct agent roles. Use its local runtime. |
| Schemas | Pydantic | Typed draft/result contracts, JSON schemas, structured model-output validation, and clear errors. |
| Database | SQLite through Python `sqlite3` | Required inventory store plus local processing ledger; explicit SQL and transactions are sufficient for MVP. |
| Money | Python `decimal.Decimal` | Exact decimal arithmetic and explicit rounding; store money as decimal strings or minor units, never binary floating-point amounts. |
| JSON/CSV/TXT | Python standard library | Direct parsing, including both supplied CSV layouts; preserve row order and source evidence. |
| XML | `defusedxml` | Parse the supplied XML invoice with hardened entity handling and application-level size limits. |
| PDF extraction | `pdfplumber` | Extract text and table evidence from text-based PDFs. Image-only OCR is not included in MVP. |
| Reasoning provider | Official xAI Python SDK, behind an application adapter | Preferred live Grok integration; select the current supported model and exact SDK calls from official documentation during implementation. |
| Offline reasoning | In-repository deterministic simulator | Predictable no-key/no-network workflow; visibly labeled simulation, with no claim of real LLM reasoning. |
| CLI | Python `argparse` | Preserve the assignment's `main.py --invoice_path=...` entry point with minimal dependency cost. |
| UI | Streamlit | Local invoice upload, evidence inspection, status dashboard, and review list using the same Python service. |
| Logging | Python `logging` with JSON serialization | Structured local events and exportable results without an external observability service. |
| Tests | Pytest | Unit, corpus, integration, and replay/failure tests; provider tests opt-in. |
| Code checks | Ruff | Formatting and linting; start with a small documented rule set. |
| Source control | Git and the user's GitHub fork | Public submission and change history; optional GitHub Issues for tracking. |

## Architecture choices

### No separate FastAPI service in the MVP

The earlier walkthrough proposed FastAPI plus Streamlit. For one local operator, Streamlit and the CLI can call the same application service in-process. This avoids managing two servers and an HTTP contract before they add value. Keep business logic outside UI code so FastAPI can be added later if another client needs it.

### LangGraph coordinates; deterministic code enforces policy

LangGraph provides orchestration. It does not make every node an LLM or require a hosted service. Use typed graph state and small services. Arithmetic, stock aggregation, required fields, duplicates, and final payment authorization remain explicit code. A full LangChain abstraction layer is optional, not a separate requirement. [Official overview](https://docs.langchain.com/oss/python/langgraph/overview).

### Model integration stays replaceable and observable

Define an internal reasoning interface for extraction assistance, approval recommendation, and critique. Implement offline and live adapters. Load credentials only for live execution and keep the chosen model configurable. Validate all model outputs through Pydantic and dispatch only approved tools.

The example SDK import and model in the assignment are illustrative; do not assume they are the current supported API. Consult [xAI's official documentation](https://docs.x.ai/overview) for the installed SDK, tool calling, structured output support, and model availability. No model name or live integration is verified by this documentation-only change.

If genuine offline inference becomes required, select a local runtime/model after checking target hardware and output/tool reliability. Do not add a large model download to default installation without resolving that decision.

### Parsing and validation

Use deterministic parsers for structured formats. For messy text, combine source extraction, known normalization rules, and optional model assistance. Preserve invalid drafts for diagnosis; a strict final payable schema should not erase evidence about missing fields. [Pydantic documentation](https://docs.pydantic.dev/latest/).

`pdfplumber` supports PDF text/table inspection; its own documentation distinguishes machine-generated PDFs from scanned inputs. We choose it for the initial text-based fixtures and will verify actual extraction quality before promising broader support. [Project documentation](https://github.com/jsvine/pdfplumber).

### Local UI

Streamlit offers a Python UI without a separate JavaScript build. Keep workflow execution behind explicit user actions and durable request identity so UI reruns cannot repeat payments. Bind locally and show simulation/live mode prominently. [Streamlit documentation](https://docs.streamlit.io/).

## Proposed repository layout

```text
main.py                         # Required CLI entry point
app.py                          # Local Streamlit entry point
pyproject.toml                  # Dependencies and tool configuration
src/invoice_processing/
  schemas.py                    # Draft, normalized, finding, result contracts
  service.py                    # Shared application entry point
  workflow.py                   # LangGraph composition
  agents/                       # Ingestion, validation, approval, payment
  parsers/                      # TXT, JSON, CSV, XML, PDF
  reasoning/                    # Provider interface, offline and xAI adapters
  policy.py                     # Approval thresholds and eligibility
  validation.py                 # Arithmetic, dates, fields, aggregation
  storage.py                    # SQLite schema and transactions
  payments.py                   # Guarded, idempotent mock service
  observability.py              # Structured events and result export
scripts/                        # Seed and demo helpers as needed
tests/                          # Unit, integration, corpus, optional live tests
data/invoices/                  # Original provided fixtures
docs/                           # These requirements/design documents
```

This tree is a plan, not a claim that the files exist. Generated databases, uploads, output logs, virtual environments, and `.env` files should be excluded from Git. Commit a secret-free configuration example when application settings are introduced.

## Dependency and verification policy

- Install only the dependencies used by the first working slice; add UI/model extras as their milestones arrive.
- Pin a tested dependency set and document Python/OS versions used for verification.
- Default tests run offline using temporary SQLite databases and controlled reasoning responses.
- Live smoke tests require explicit opt-in and report provider/model and result without exposing secrets.
- Check format/lint, unit tests, end-to-end corpus behavior, duplicate payment invariants, and a manual UI smoke test before submission.
- Optional CI may run these checks on GitHub; cloud hosting of the application is outside scope.

Matt Pocock's skills are development-workflow aids, not runtime dependencies. Their setup and issue-tracker conventions remain a separate task; no skills are installed by this document.
