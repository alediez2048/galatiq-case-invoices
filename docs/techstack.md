# Technology stack

Status: user-approved stack direction after two grilling rounds; dependencies are not yet installed. See [decisions](decisions.md). This is a local React frontend with a Python backend. Package versions will be selected, tested together, and locked when the environment is created; no unverified “latest” pins are prescribed here.

Related: [requirements](requirements.md), [constraints](contraints.md), [system design](systemsdesign.md).

## Selected baseline

| Area | Proposed tool | Purpose and rationale |
| --- | --- | --- |
| Runtime | Python 3.12 | Backend language for parsing, agents, persistence, CLI, API, and tests. Validate dependency compatibility before locking. |
| Environment | `venv`, `pip`, `pyproject.toml`, pinned dependency lock/requirements export | Conventional local setup and reproducible installs. Choose the concrete locking workflow during scaffolding. |
| Orchestration | LangGraph | Explicit graph state, conditional routing, bounded repair/critique paths, and distinct agent roles. Use its local runtime. |
| Schemas | Pydantic | Typed draft/result contracts, JSON schemas, structured model-output validation, and clear errors. |
| Database | SQLite through Python `sqlite3` | Required inventory store plus local processing ledger; explicit SQL and transactions are sufficient for MVP. |
| Money | Python `decimal.Decimal` | Exact decimal arithmetic and explicit rounding; store money as decimal strings or minor units, never binary floating-point amounts. |
| JSON/CSV/TXT | Python standard library | Direct parsing, including both supplied CSV layouts; preserve row order and source evidence. |
| XML | `defusedxml` | Parse the supplied XML invoice with hardened entity handling and application-level size limits. |
| PDF extraction | `pdfplumber` | Extract text and table evidence from text-based PDFs. Image-only OCR is not included in MVP. |
| Reasoning provider | Official xAI Python SDK, behind an application adapter | Required primary-demo Grok integration; select the current supported model and exact SDK calls from official documentation during implementation. |
| Offline reasoning | In-repository deterministic simulator | Predictable no-key/no-network workflow; visibly labeled simulation, with no claim of real LLM reasoning. |
| CLI | Python `argparse` | Preserve the assignment's `main.py --invoice_path=...` entry point with minimal dependency cost. |
| UI | React + TypeScript | Preserve the approved mockup, with invoice upload, evidence inspection, controlled corrections, and human approval. |
| HTTP API | FastAPI | Typed local API delegating to the Python processing service also used by the CLI. |
| Frontend environment | Node.js + npm, proposed Vite build tooling | Local frontend development and production build; commit a tested lockfile and keep all runtime assets local for offline use. |
| Logging | Python `logging` with JSON serialization | Structured local events and exportable results without an external observability service. |
| Tests | Pytest | Unit, corpus, integration, and replay/failure tests; live-provider checks explicitly invoked and required before claiming the primary demo works. |
| Code checks | Ruff | Formatting and linting; start with a small documented rule set. |
| Source control | Git and the user's GitHub fork | Public submission and change history; optional GitHub Issues for tracking. |

## Architecture choices

### React and FastAPI preserve the approved experience

The user approved replacing the earlier Streamlit proposal with React + TypeScript and FastAPI. The approved HTML mockup is the visual baseline. React owns presentation and interactions; FastAPI owns request validation and delegates business operations to the shared Python service. The CLI calls that same service directly. Do not duplicate policy in browser code.

The frontend and backend add setup/build work, accepted in exchange for preserving the intended interface. Lock compatible versions during scaffolding. Node.js/Vite are implementation proposals within the approved stack, not additional user-confirmed package/version decisions.

### LangGraph coordinates; deterministic code enforces policy

LangGraph provides orchestration. It does not make every node an LLM or require a hosted service. Use typed graph state and small services. Arithmetic, stock aggregation, required fields, duplicates, and final payment authorization remain explicit code. A full LangChain abstraction layer is optional, not a separate requirement. [Official overview](https://docs.langchain.com/oss/python/langgraph/overview).

### Model integration stays replaceable and observable

The primary demo must exercise real Grok; offline simulation remains an explicitly selected reproducibility path, never an automatic fallback. Define an internal reasoning interface for extraction assistance, approval recommendation, and critique. Implement offline and live adapters. Load credentials only for live execution and keep the chosen model configurable. Validate all model outputs through Pydantic and dispatch only approved tools.

The example SDK import and model in the assignment are illustrative; do not assume they are the current supported API. Consult [xAI's official documentation](https://docs.x.ai/overview) for the installed SDK, tool calling, structured output support, and model availability. No model name or live integration is verified by this documentation-only change.

If genuine offline inference becomes required, select a local runtime/model after checking target hardware and output/tool reliability. Do not add a large model download to default installation without resolving that decision.

### Parsing and validation

Use deterministic parsers for structured formats. For messy text, combine source extraction, known normalization rules, and optional model assistance. Preserve invalid drafts for diagnosis; a strict final payable schema should not erase evidence about missing fields. [Pydantic documentation](https://docs.pydantic.dev/latest/).

`pdfplumber` supports PDF text/table inspection; its own documentation distinguishes machine-generated PDFs from scanned inputs. We choose it for the initial text-based fixtures and will verify actual extraction quality before promising broader support. [Project documentation](https://github.com/jsvine/pdfplumber).

### Local UI

React implements the approved layout and reusable components. Processing, corrections, and human approvals use explicit actions through FastAPI; page refreshes and repeated requests cannot repeat payment. Preserve the mockup's appearance while adding source-backed correction forms, required reasons, revalidation, and eligible high-value approval. Bind services locally and show each run's live/simulation mode prominently. The static HTML prototype remains an appearance reference, not the React application.

## Proposed repository layout

```text
main.py                         # Required CLI entry point
frontend/                       # React + TypeScript UI, styles, build configuration
frontend/package-lock.json      # Tested frontend dependency lock
pyproject.toml                  # Dependencies and tool configuration
src/invoice_processing/
  schemas.py                    # Draft, normalized, finding, result contracts
  api.py                        # FastAPI entry point and HTTP boundary
  service.py                    # Shared CLI/API application entry point
  review.py                     # Versioned corrections and human approval
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
tests/                          # Unit, integration, corpus, explicitly invoked live tests
data/invoices/                  # Original provided fixtures
docs/                           # These requirements/design documents
```

This tree is a plan, not a claim that the files exist. Generated databases, uploads, output logs, virtual environments, and `.env` files should be excluded from Git. Commit a secret-free configuration example when application settings are introduced.

## Dependency and verification policy

- Install only the dependencies used by the first working slice; add frontend/API and model dependencies as their milestones arrive.
- Pin a tested dependency set and document Python/OS versions used for verification.
- Default tests run offline using temporary SQLite databases and controlled reasoning responses.
- Live smoke tests require explicit invocation and report provider/model and result without exposing secrets. They are required evidence for the primary demo, while ordinary CI stays offline.
- Add frontend type/build checks and browser coverage for correction/revalidation, human approval, and rejection of stale or repeated actions.
- Check format/lint, unit tests, end-to-end corpus behavior, duplicate payment invariants, and a manual UI smoke test before submission.
- Optional CI may run these checks on GitHub; cloud hosting of the application is outside scope.

Matt Pocock's skills are development-workflow aids, not runtime dependencies. Their setup and issue-tracker conventions remain a separate task; no skills are installed by this document.
