# Phase 3 — Live Grok Reasoning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tasks marked **[SDD]** get an implementer, a task review and a fix loop; tasks marked **[light]** get one implementer and are covered only by the final whole-branch review (user decision 2026-11-01: full review only for payment-safety and model-facing work).

**Goal:** live mode runs the agents on real Grok through the official `xai_sdk` with whitelisted tools, structured outputs, a bounded recommend → critique → revise loop, evidence-checked extraction assist and explicit retry — all exercised offline against a scripted fake client, so only the live smoke test (P3-10) waits for the user's xAI key.

**Architecture:** a `ReasoningProvider` protocol (offline simulator and `XaiProvider`) now receives a per-run `ModelSession` carrying the tool dispatcher and the call budget. `XaiProvider` drives `client.chat.create(...)` / `chat.append` / `chat.sample` / `chat.parse` with a client factory (real `xai_sdk.Client` in production, `tests/fakes/xai_client.py` in tests). Tool calls go through `tools.Dispatcher`, which validates agent authorization and Pydantic arguments and only ever reads. Model errors become stable codes; the node catches them and fails the run as recoverable; `service.retry_run` re-processes a failed run in the same mode. The deterministic policy gate and the guarded payment service are unchanged and remain the only path to payment.

**Tech Stack:** Python 3.12, uv, Pydantic 2, SQLite, LangGraph 1.2, `xai-sdk` 1.21 (gRPC), `python-dotenv` 1.x, pytest, ruff.

**Spec:** `docs/PRD.md` (Phase 3), `docs/decisions.md` (round 2 #4, round 3 #1/#3), `docs/contraints.md` (operational bounds, security and trust boundaries), `docs/systemsdesign.md` (agents and tools, processing sequence), tickets `docs/tickets/P3-01` … `P3-10`, and the "Phase 1 carry-overs" rows for P3-01 / P3-07 / P3-08 in `docs/tickets/README.md`.

## Global Constraints

- Offline mode never imports `xai_sdk`, never reads `XAI_*` settings, opens no socket, and its outcomes for all 20 samples stay exactly as `tests/test_acceptance.py` asserts.
- Live mode is explicit (`--mode live`); credentials load only then. Missing `XAI_API_KEY` or `XAI_MODEL` → configuration error before any run row exists. No hard-coded model default.
- The API key never appears in logs, results, audit events, exceptions, prompts or `repr` (sentinel-value tests).
- No model output can authorize payment: the deterministic gate (`policy.evaluate`) and `payments.pay` decide; no tool writes, pays or changes policy.
- Bounds: request timeout 30 s (`XAI_TIMEOUT_SECONDS`), ≤ 2 transport attempts for transient errors only, budget 6 top-level model steps per invoice (`MODEL_CALL_BUDGET`), ≤ 3 model turns per step's tool loop, one extraction repair, one critique, at most one revision.
- Invoice text is untrusted data: always inside an escaped, delimited data block; excerpts ≤ 4,000 characters per call; never other invoices' data, environment or keys.
- Persist short summaries, codes, cited evidence, tool calls, provider/model/SDK/prompt versions, latency and token usage; never hidden reasoning (`reasoning_content`) or full prompts.
- Tests need no credentials and no network (autouse `no_network` guard; the guard is extended to `socket.connect_ex` and `socket.getaddrinfo` in Task 1).
- Money stays `Decimal`; finding/error codes are stable identifiers; tests assert codes and statuses, not prose.
- `uv run ruff check .` and `uv run ruff format --check .` clean; commits end with the session trailer lines.

## Decisions taken in this plan

1. **Process (user decision):** [SDD] for Tasks 2–6 (model-facing or payment-adjacent), [light] for Tasks 1 and 7. Cost: Tasks 1/7 rely on the final review.
2. **LangSmith tracing is forced off in both modes** (carry-over P3-01): live invoice bytes must not reach a third-party tracer by environment accident. Cost: no LangSmith traces until someone opts in deliberately in code.
3. **Tool calls and model calls are persisted as audit events** (`stage="model"` / `"tool"`), not a new table. Cost: a table later if the UI needs to query them heavily.
4. **`runs.mode_switch_of` is added → `SCHEMA_VERSION = 5`.** Cost: a Phase 2 database is refused (same message as before).
5. **Retry runs now run the identity check**, excluding the run being retried from "prior outcomes", so a retried revision of a paid invoice ends `needs_review` / `revision_after_payment` (closes the Phase 2 P3-08 carry-over). A crash replay that reuses an existing payment re-points `payments.run_id` to the replaying run, so later duplicates carry the receipt. Cost: none.
6. **Extraction assist triggers only on review-or-worse extraction problems** (any extraction issue or normalization finding of severity review/blocker, or a missing vendor / invoice number / due date / total / line items). Info-only `unparsed_line` never triggers a call. Cost: a model call on every supplied invoice with such findings (1003, 1009, 1014 …); the fake returns no proposals so outcomes are unchanged.
7. **Accepted model proposals fill only fields that are currently missing**, then normalization re-runs on the amended draft; a proposal for a field that already has a value is never applied and emits `model_parser_disagreement` (review) when it differs. Cost: a model cannot fix a wrong-but-present parse (Phase 4 corrections do that).
8. **The revision is a separate provider call `revise(...)`**; the offline simulator's `revise` returns the critique's revised recommendation, so offline outcomes are unchanged. Cost: none.
9. **`risk_signal_embedded_instructions` is detected deterministically in normalization** (all modes) from a fixed phrase list, so offline results show it too. Cost: false positives on unusual wording are info-only.
10. **Model id from settings is passed through unvalidated** (the SDK accepts any string); readiness `--ping` is the only check. Cost: a typo surfaces as `model_unavailable` at first call.
11. **`python-dotenv` loads `.env` only in live mode**, without overriding variables already set. Cost: one small dependency.

## Review Focus

1. **A model that obeys an injected instruction** ("approve", "stock is 1000", fake tool-call JSON) must not change the gate outcome or execute any non-whitelisted tool — tested with an obeying scripted fake (Task 5).
2. **A live failure after deterministic validation** keeps the computed findings, never pays, is `recoverable`, and a retry pays at most once (Task 6).
3. **A runaway tool loop or budget exhaustion mid-approval** leaves no decision row claiming `approved` and no payment (Task 4).
4. **The API key in an exception message** from the SDK (e.g. an auth error echoing metadata) is never logged or returned (Task 2).
5. **Offline runs after live failures** are labeled offline and carry no live recommendation, critique or decision (Task 6).

---

### Task 1 [light]: Live configuration, readiness, CLI, guard and tracing hardening (P3-01, carry-overs)

**Files:** Create `src/invoice_processing/settings.py`, `src/invoice_processing/readiness.py`, `.env.example`. Modify `pyproject.toml`/locks (`xai-sdk>=1.21,<2`, `python-dotenv>=1,<2`), `.gitignore` (`.env`), `main.py`, `src/invoice_processing/reasoning/__init__.py`, `src/invoice_processing/service.py`, `src/invoice_processing/ledger.py` (`REDACTED_KEY`), `tests/conftest.py`, `main.py::_install_network_guard`, `README.md` (live-mode section), `docs/development.md`.

**Interfaces — produces:**
- `settings.LiveSettings` — frozen dataclass `api_key: str`, `model: str`, `timeout_seconds: float = 30.0`, `call_budget: int = 6`, `tool_turn_cap: int = 3`, `excerpt_chars: int = 4000`; `__repr__`/`__str__` mask the key as `"***"`.
- `settings.load_live_settings(env: Mapping[str, str] | None = None) -> LiveSettings` — loads `.env` (python-dotenv, `override=False`) only when `env is None`; raises `settings.ConfigurationError(message)` naming missing variables (`XAI_API_KEY`, `XAI_MODEL`) or invalid numbers (`XAI_TIMEOUT_SECONDS`, `MODEL_CALL_BUDGET`), never their values.
- `reasoning.get_provider(mode, *, settings: LiveSettings | None = None, client_factory: Callable[[LiveSettings], Any] | None = None) -> ReasoningProvider` — live: loads settings if not given and returns `XaiProvider` (Task 2; until then raise `ProviderUnavailable("live provider arrives in Task 2")` after settings load succeed). `ConfigurationError` subclasses `ProviderUnavailable` so `main.py`'s existing exit-2 path covers it. Offline path imports nothing from `xai_sdk`.
- `service.process_invoice(..., provider: ReasoningProvider | None = None)` — tests inject a provider; `None` keeps `get_provider(mode)`.
- CLI: `--mode live` prints `Mode: live model (<model>) — invoice text will be sent to xAI` on stderr.
- `python -m invoice_processing.readiness [--ping]` — prints one line per setting `XAI_API_KEY: set|missing`, `XAI_MODEL: <name>|missing`, timeout, budget; exit 0 if ready else 2; `--ping` makes one minimal SDK call (only path that touches the network) and prints `ping: ok (<model>, <latency_ms> ms)` or the error code.
- LangSmith: `service.process_invoice` wraps the graph in `langsmith.tracing_context(enabled=False)` in **both** modes (Decision 2).
- `REDACTED_KEY` also matches camelCase `clientSecret`, `sessionToken`, `apiKey` and the literal `xai_api_key`.
- Network guard (conftest + `main._install_network_guard`) also blocks `socket.socket.connect_ex` and `socket.getaddrinfo`.

**Tests (write first):**
- `tests/test_settings.py`: missing key / missing model / bad budget → `ConfigurationError` whose message names the variable and does not contain the sentinel value `"sk-SENTINEL-123"`; `repr(load_live_settings({...}))` has no sentinel; `.env` is not read when `env` is passed.
- `tests/test_cli.py`: `--mode live` with no env → exit 2, `XAI_API_KEY` in stderr, no `runs` row; with `XAI_API_KEY=sk-SENTINEL-123 XAI_MODEL=grok-test` the banner names `grok-test` and stderr/stdout/events never contain the sentinel.
- `tests/test_offline_imports.py`: a subprocess runs one offline invoice and asserts `"xai_sdk" not in sys.modules` afterwards.
- `tests/test_readiness.py`: no env → exit 2 and `XAI_API_KEY: missing`; with env → exit 0, value never printed; `--ping` not exercised (network).
- `tests/test_network_guard.py`: `socket.getaddrinfo("example.com", 443)` and `socket.socket().connect_ex(("127.0.0.1", 9))` raise in tests.
- `tests/test_ledger.py`: the four new redacted names.

- [ ] Steps: failing tests → implement → full suite + ruff → commit `feat: live-mode settings, readiness check, CLI banner and guard hardening`.

---

### Task 2 [SDD]: xAI adapter, model sessions, error classification and the scripted fake client (P3-02, P3-09 fake)

**Files:** Create `src/invoice_processing/reasoning/session.py`, `src/invoice_processing/reasoning/xai.py`, `src/invoice_processing/reasoning/errors.py`, `src/invoice_processing/reasoning/schema_check.py`, `tests/fakes/__init__.py`, `tests/fakes/xai_client.py`. Modify `reasoning/base.py`, `reasoning/offline.py`, `reasoning/__init__.py`, `schemas.py`, `codes.py`, `agents/approval.py` (pass a session; behaviour unchanged).

**Interfaces — produces:**
- `codes.ModelErrorCode(StrEnum)`: `model_auth_error`, `model_rate_limited`, `model_timeout`, `model_unavailable`, `model_output_invalid`, `model_refused`, `model_budget_exhausted`, `model_tool_loop_exceeded`.
- `reasoning.errors.ModelError(code: ModelErrorCode, message: str)` with `.code`, `.recoverable = True`; message never includes the API key or SDK metadata (classifier builds its own message from the gRPC status code).
- `reasoning.errors.classify(exc: BaseException) -> ModelError` — `grpc.RpcError.code()`: `DEADLINE_EXCEEDED` → timeout; `UNAVAILABLE`, `INTERNAL`, `UNKNOWN` → unavailable; `RESOURCE_EXHAUSTED` → rate_limited; `UNAUTHENTICATED`, `PERMISSION_DENIED` → auth_error; `INVALID_ARGUMENT`, `NOT_FOUND`, `FAILED_PRECONDITION` → unavailable (non-transient); `TimeoutError` → timeout; `ConnectionError` → unavailable; anything else → unavailable. `TRANSIENT = {timeout, rate_limited}` plus gRPC `UNAVAILABLE` (the classifier marks transience on the returned error: `.transient: bool`).
- `reasoning.session.ModelSession` — per run: `budget: int`, `used: int` (top-level steps incl. transport retries), `tool_turn_cap: int`, `tools: ToolBox` (Task 3; until then a `NullToolBox` with `specs(agent) -> []`), `calls: list[ModelCallRecord]`; method `charge() -> None` raises `ModelError(model_budget_exhausted)` **before** a step when `used >= budget`, else increments. `ModelCallRecord(step, attempt, latency_ms, input_tokens, output_tokens, tool_turns)`.
- `reasoning.base.ReasoningProvider` protocol, each method takes `session: ModelSession` as the last argument:
  - `recommend(invoice, findings, policy, session) -> ApprovalRecommendation`
  - `critique(invoice, findings, recommendation, policy, session) -> Critique`
  - `revise(invoice, findings, recommendation, critique, policy, session) -> ApprovalRecommendation`
  - `assist_extraction(request: ExtractionAssistRequest, session) -> ExtractionProposals` (types defined here; Task 5 uses them)
  - attributes `mode`, `provider`, `model`, `prompt_version`.
- `OfflineSimulator`: same outcomes as today; `revise` returns its critique's `revised_recommendation` as an `ApprovalRecommendation`; never touches the session (so `used == 0`).
- `XaiProvider(settings: LiveSettings, client_factory: Callable[[LiveSettings], Any])` — `provider = "xai"`, `model = settings.model`, records `xai_sdk` version. Per step: `session.charge()`; `chat = client.chat.create(model=..., messages=[system(prompt), user(data)], tools=[tool(...) for spec in session.tools.specs(agent)])`; tool loop: `response = chat.sample()`; while `response.tool_calls` and turns < cap: for each call append `tool_result(session.tools.call(agent, name, arguments_json), tool_call_id=call.id)`; turns == cap with pending tool calls → `ModelError(model_tool_loop_exceeded)`; final structured output via `chat.parse(OutputModel)` then `OutputModel.model_validate(obj.model_dump())` locally; validation failure → `model_output_invalid`; empty/refusal finish reason → `model_refused`. Transport: wrap each SDK call, classify, retry once if transient — the retry calls `session.charge()` again (counts against budget). Records a `ModelCallRecord` (no prompt text).
- `reasoning.schema_check.unsupported_keywords(schema: dict) -> list[str]` — walks a JSON schema and returns any of `not`, `if`, `then`, `else`, or an `allOf` with more than one subschema; root must be `type: object`.
- `tests/fakes/xai_client.py`: `FakeXaiClient(script: list[Step])` mirroring `client.chat.create(...) -> FakeChat` with `append`, `sample`, `parse`; steps: `Parsed(obj)`, `ToolCalls([(name, args_dict)])`, `Malformed(text)`, `Raise(grpc_code | exception)`; records every request (model, tool names, message roles, content length) for assertions; `client_factory = lambda settings: FakeXaiClient(script)`.
- `ApprovalDecision` gains `prompt_version: str | None`, `model_calls_used: int = 0`; `ProcessingResult` gains `model_calls_used: int = 0`, `model_calls_budget: int | None = None`, `recoverable: bool = False`, `next_actions: list[str] = []`.

**Tests (write first)** in `tests/test_reasoning_xai.py`, `tests/test_reasoning_errors.py`, `tests/test_schema_check.py`:
- fake returns a valid parsed `ApprovalRecommendation` payload → `recommend` returns it with `mode=live`, `provider="xai"`, `model="grok-test"`; one `ModelCallRecord`.
- `Raise(DEADLINE_EXCEEDED)` then success → exactly 2 requests, `session.used == 2`; timeout twice → `ModelError(model_timeout)`.
- `Raise(UNAUTHENTICATED)` → `model_auth_error` after 1 request (not retried); `RESOURCE_EXHAUSTED` once then success → 2 requests.
- `Malformed("not json")` / schema-violating object → `model_output_invalid`.
- An SDK exception whose details contain `"sk-SENTINEL-123"` → the `ModelError` message does not contain it.
- `unsupported_keywords` is `[]` for `ApprovalRecommendation`, `Critique`, `ExtractionProposals` JSON schemas; a hand-made schema with `not` is reported.
- Budget: `ModelSession(budget=1)`; two `charge()` calls → second raises `model_budget_exhausted`.
- All Phase 1–2 tests stay green (offline outcomes unchanged).

- [ ] Steps: failing tests → implement → full suite + ruff → commit `feat: xAI reasoning adapter with sessions, error codes and a scripted fake client`.

---

### Task 3 [SDD]: Whitelisted tool registry and dispatcher (P3-03)

**Files:** Create `src/invoice_processing/tools.py`. Modify `reasoning/session.py` (real `ToolBox`), `agents/state.py` (build the session per run), `tests/test_tools.py`.

**Interfaces — produces:**
- `tools.ToolSpec` — `name`, `description`, `args_model: type[BaseModel]`, `handler: Callable[[ToolContext, BaseModel], dict]`, `allowed_agents: frozenset[str]`; `json_schema()` = `args_model.model_json_schema()` (object root, `additionalProperties: false`).
- `tools.ToolContext` — `conn`, `run_id`, `invoice: NormalizedInvoice | None`, `invoice_id`, `version_id`, `source_text: str | None` (decoded TXT or extracted PDF text; JSON/CSV/XML raw text).
- `tools.REGISTRY: dict[str, ToolSpec]` with exactly: `lookup_inventory(items: list[str] ≤ 200)` {validation, approval}; `recompute_totals()` {validation, approval}; `get_findings(severity: Severity | None)` {approval}; `lookup_prior_invoice()` {validation, approval} (versions, run outcomes, payment status for this identity — no receipts' internal ids beyond `receipt_id`); `get_source_excerpt(location: str)` {ingestion, approval} (bounded to `excerpt_chars`, located by evidence location `line:N` / `page:P,line:N` / JSON path / `row:N` / element path; unknown location → `tool_rejected`); `list_item_aliases()` {ingestion}.
- `tools.Dispatcher(ctx, *, excerpt_chars)` implementing `ToolBox`: `specs(agent) -> list[ToolSpec]` (only the agent's allowed tools); `call(agent, name, arguments_json: str) -> str` — returns JSON text; unknown tool, unauthorized agent, non-JSON or invalid arguments → `{"error": "tool_rejected", "reason": "<unknown_tool|unauthorized|invalid_arguments>"}`; handler exceptions → `{"error": "tool_failed"}`; never raises. Every call emits an audit event (`stage="tool"`, `event="tool_call"`, payload: agent, tool, validated args, `ok`, error reason, result size, duration_ms — never the excerpt text itself).
- No tool writes to the database: handlers receive a read-only connection wrapper (`ReadOnlyConnection` exposing `execute` that rejects statements not starting with `SELECT`).

**Tests (write first)** `tests/test_tools.py`:
- approval calling `list_item_aliases` → `tool_rejected` / `unauthorized`; `lookup_inventory` with `{"items": "WidgetA"}` → `invalid_arguments`; `{"items": [...201 names]}` → `invalid_arguments`; unknown tool → `unknown_tool`; malformed JSON → `invalid_arguments`.
- `lookup_inventory(["WidgetA","FakeItem","Nope"])` → `{WidgetA: 15, FakeItem: 0, Nope: null}`; inventory unchanged after 50 random calls.
- `REGISTRY` keys equal the six names; no name contains `pay`, `write`, `update`, `delete`, `approve`, `policy`.
- every `json_schema()` has an object root and `unsupported_keywords(...) == []`.
- audit events recorded per call with no excerpt text.
- `get_source_excerpt("line:9")` on INV-1001 returns that line; length capped at `excerpt_chars`.

- [ ] Steps: failing tests → implement → full suite + ruff → commit `feat: whitelisted read-only tool registry and dispatcher`.

---

### Task 4 [SDD]: Live approval, critique, one revision, budget wiring and threshold fixtures (P3-04, P3-06)

**Files:** Create `src/invoice_processing/reasoning/prompts/recommend.v1.md`, `critique.v1.md`, `revise.v1.md`, `src/invoice_processing/reasoning/prompting.py`, `tests/fixtures/threshold/valid_10000_00.json`, `valid_10000_01.json`. Modify `agents/approval.py`, `agents/state.py`, `service.py`, `codes.py`, `schemas.py`, `reasoning/xai.py`, `reasoning/offline.py`, `docs/tickets/P3-04*.md` (document worst-case requests = budget × (1 + tool cap)).

**Interfaces — produces:**
- `codes.CritiqueIssue(StrEnum)`: `uncited_blocker`, `unsupported_claim`, `missed_high_value_scrutiny`; `Critique` gains `issues: list[CritiqueIssue] = []`.
- `reasoning.prompting.load_prompt(name: str) -> tuple[str, str]` (text, version `"<name>.v1"`); `data_block(text: str) -> str` wraps text in `<<<INVOICE_DATA` … `INVOICE_DATA>>>` after escaping any occurrence of either delimiter in the text; `invoice_payload(invoice, findings, policy) -> str` (JSON of normalized fields and finding codes — no raw source) used for recommend/critique/revise.
- `agents/approval.run`: `initial = provider.recommend(...)`; `critique = provider.critique(...)`; deterministic checks append issues: every blocker code missing from the recommendation's `cited_codes` (when it recommends approve or review) → `uncited_blocker`; stated total > threshold and the recommendation summary/reasons do not mention the threshold → `missed_high_value_scrutiny`; if the critique disagrees or has issues → `revised = provider.revise(...)` (exactly once); final = revised or initial; then the existing gate. `ModelError` from any call → state `status=failed`, `error_code=<code>`, `error_message="Model request failed. Payment was not attempted."`, no decision row; the graph's route sends `failed` to end. Findings already computed are kept in state and the ledger.
- Decision persistence gains: critique issues, revised recommendation, provider/model, `prompt_version`, `model_calls_used`; audit events `recommendation`, `critique` (with issues), `revision`, `decision`; per-model-call audit events `stage="model"` from `session.calls`.
- `service._result` fills `model_calls_used`, `model_calls_budget` (None offline), `recoverable` (True for any `ModelErrorCode`), `next_actions` (`["retry", "run offline as a separate simulation"]` when recoverable).
- Threshold fixtures: JSON, USD, vendor "Threshold Test Supply", lines WidgetA 15 × 250.00, WidgetB 10 × 500.00, GadgetX 1 × 750.00 (subtotal 9,500.00), tax 0, shipping 500.00 / 500.01, totals 10,000.00 / 10,000.01, due 2026-02-28, invoice numbers TH-10000-00 / TH-10000-01.

**Tests (write first)** `tests/test_live_approval.py` (all through `process_invoice(..., mode=live, provider=XaiProvider(settings, fake_factory))` on fresh seeded dbs, evaluation date 2026-01-31):
- fake recommends approve (no cited codes) on INV-1002 → critique issues include `uncited_blocker`; final status `rejected`; no payment.
- fake recommends reject on INV-1001, critique agrees, no revision → `awaiting_human_approval` with `model_disagreement`; then `ledger` records a human approve for that version and a second run pays (one payment); a decline instead → never paid.
- clean `valid_10000_01.json` with a recommendation that cites the threshold → `awaiting_human_approval`, critique issues empty; `valid_10000_00.json` approve → `paid_mock` 10000.00 (offline too).
- call counts: exactly one critique request and at most one revision request per run.
- tool loop: a fake that returns `ToolCalls` on every sample → `failed`, `model_tool_loop_exceeded`, recoverable, no decision row, no payment; a recommendation that uses 3 tool turns then parses → consumes one budget unit.
- budget 2 with a critique that disagrees → `failed`, `model_budget_exhausted` before the revision request (2 requests made).
- a transport timeout once on recommend → `model_calls_used == 3` for recommend + critique.
- offline INV-1001 → `model_calls_used == 0`, `model_calls_budget is None`.

- [ ] Steps: failing tests → implement → full suite + ruff → commit `feat: live recommend-critique-revise loop with budget, tool loop cap and threshold fixtures`.

---

### Task 5 [SDD]: Extraction assist with evidence check, one repair, and untrusted-input safeguards (P3-05, P3-07)

**Files:** Create `src/invoice_processing/assist.py`, `src/invoice_processing/reasoning/prompts/extract.v1.md`, `tests/fixtures/adversarial/approve_me.txt`, `manager_approved.txt`, `fake_tool_call.txt`, `stock_updated.txt`. Modify `agents/ingestion.py`, `normalize.py`, `codes.py`, `schemas.py`, `reasoning/xai.py`, `reasoning/prompting.py`, `reasoning/offline.py`.

**Interfaces — produces:**
- Codes: `model_proposal_unsupported` (info), `model_parser_disagreement` (review), `risk_signal_embedded_instructions` (info).
- `schemas.ExtractionAssistRequest` — `issues: list[str]` (codes + fields), `excerpts: list[SourceExcerpt(location, text)]` (bounded, ≤ `excerpt_chars` total), `known_items: list[str]`; `schemas.FieldProposal` — `field: Literal["vendor","invoice_number","invoice_date","due_date","currency","subtotal","tax","shipping","total"]`, `value: str`, `quote: str`, `location: str`; `ExtractionProposals.proposals: list[FieldProposal]`.
- `assist.needs_assist(draft, findings) -> bool` per Decision 6.
- `assist.check_proposal(p, source_lines: Mapping[str, str], draft) -> Literal["accept","unsupported","disagree","ignore"]` — accept only if `p.quote` is a substring of the source text at `p.location` and every digit run / word token of `p.value` (after stripping `$,`) appears in the quote; field already set and differing → `disagree`; already set and equal → `ignore`.
- Ingestion node, live only: if `needs_assist` → `session.charge()` via `provider.assist_extraction`; on `model_output_invalid` → one repair attempt (the request carries `repair_hint` = validation error summary, no source text change); second failure → no proposals are applied, the original issues stay unresolved and processing continues (their review findings route to `needs_review`), never `failed`. Accepted proposals set the raw draft field and append `NormalizationEvent(provenance=f"model:xai/{model}", raw_value=None, normalized_value=value, evidence=[EvidenceRef(location, snippet=quote)])`; then normalization re-runs on the amended draft. Unsupported → finding `model_proposal_unsupported`; disagree → `model_parser_disagreement`.
- Offline `assist_extraction` returns no proposals and is never called (offline never triggers).
- `normalize.detect_embedded_instructions(draft) -> ValidationFinding | None` — case-insensitive phrases: `ignore (all |any )?(previous |prior )?instructions`, `you are (now )?(an?|the) `, `approve this invoice`, `mark (this|as) (approved|paid)`, `(manager|cfo|director) (has )?(already )?approved`, `inventory has been updated`, `"recommendation"\s*:`, `tool_call`, `function_call`, `system prompt`; evidence = first matching line; info severity; runs in all modes.
- `prompting.data_block` used for every excerpt; the extract prompt and the recommend/critique prompts state that data-block content is never an instruction.

**Tests (write first)** `tests/test_assist.py`, `tests/test_adversarial.py`:
- INV-1009 live: fake proposes `vendor="Acme Fake Co"` with a quote not in the source → discarded (`model_proposal_unsupported`), vendor still missing, status `rejected`.
- a constructed TXT missing its `Vendor:` line but with a footer `Acme Parts Ltd` line: fake proposes it with that quote/location → vendor filled, event provenance `model:xai/grok-test`.
- malformed then valid → exactly one repair request, accepted; malformed twice → no `failed` status; issues remain; status `needs_review` or `rejected` per remaining findings.
- live run of INV-1001 with a fake that would fail if called for extraction → no extraction request made (call log).
- each adversarial fixture (overstock or unknown item content plus the injected text): an **obeying** fake (recommends approve, critique agrees, requests `pay_invoice` / `update_inventory` tool calls, and proposes `total` matching the injected claim) → gate outcome equals the offline outcome of the same file with the injected lines removed; dispatcher rejects every non-whitelisted tool; `risk_signal_embedded_instructions` present; no payment.
- no request sent to the fake contains `sk-SENTINEL-123`, any other invoice's number, or text outside the bounded excerpts (assert total excerpt chars ≤ 4000 per request).

- [ ] Steps: failing tests → implement → full suite + ruff → commit `feat: evidence-checked extraction assist and prompt-injection safeguards`.

---

### Task 6 [SDD]: Live failure handling, explicit retry and mode switch (P3-08, Phase 2 carry-overs)

**Files:** Modify `storage.py` (`SCHEMA_VERSION = 5`, `runs.mode_switch_of TEXT REFERENCES runs(run_id)`), `ledger.py` (`start_run(..., retry_of=None, mode_switch_of=None)`, `check_identity` per Decision 5, payment re-point on replay), `payments.py`, `service.py` (`retry_run`), `agents/ingestion.py`, `main.py` (`--retry RUN_ID`), `docs/development.md`, `docs/tickets/README.md` (strike the P3-08 carry-over row).

**Interfaces — produces:**
- `service.retry_run(run_id: str, path, db_path, evaluation_date, events=None, provider=None) -> ProcessingResult` — the ledger stores no source bytes, so the caller re-supplies the file; refuses with `service.RetryRefused(reason)` where reason is `not_failed` (run not `failed`), `not_recoverable` (`error_code` not a `ModelErrorCode` value, `interrupted` or `unexpected_error`) or `source_mismatch` (sha256 of the file ≠ the run's source `content_hash`). Otherwise a new run in the original run's mode with `retry_of=run_id`.
- A run whose source previously ran in the other mode gets `mode_switch_of` = latest run id of that source in the other mode and skips the byte-level duplicate check; it never reads earlier decisions (decisions are per run already — assert it).
- `check_identity` for retries: still evaluates rules 1 and 3 (payment / other version) but excludes the retried run and its own retry chain from "prior outcomes"; never returns `duplicate` for a retry.
- `payments.pay` same-version replay branch updates `payments.run_id` to the replaying run.
- CLI: `python main.py --retry RUN_ID --invoice_path=PATH [--mode ...ignored; the original mode is used]` prints `Retrying run <id> (failed: <code>)` then the normal summary; refusal → exit 2 with the reason.
- Failure result: `errors=[code]`, `error_message="Model request failed. Payment was not attempted."`, `recoverable=True`, `next_actions=["retry", "run offline as a separate simulation"]`.

**Tests (write first)** `tests/test_retry.py`:
- live INV-1001 with fake `Raise(UNAVAILABLE)` ×2 → `failed`, `model_unavailable`, recoverable, message as above, no payment; `retry_run` with a working fake → new run `retry_of` set, `paid_mock`, one payment total.
- `retry_run` on a `paid_mock` run, on a failed run with `error_code="txt_decode_error"`, and with a different file → `RetryRefused` (`not_failed`, `not_recoverable`, `source_mismatch`).
- offline run of the same file after the failed live run → `mode=offline`, `mode_switch_of` = the live run, decision row has `mode=offline`, `provider="offline"`; one payment.
- retry of a failed revision run of a paid invoice (1004 paid, 1004_revised live run fails) → retry ends `needs_review` with `revision_after_payment`.
- crash replay then exact re-submission → `duplicate` with the receipt (payments.run_id re-pointed).
- grep-style test: `reasoning/__init__.py` and `service.py` contain no code path that returns `OfflineSimulator` when `mode == live` (behaviour test: live with a failing settings load raises, never returns an offline result).
- schema v4 database refused with `SchemaVersionError`.

- [ ] Steps: failing tests → implement → full suite + ruff → commit `feat: recoverable live failures, explicit retry and labeled mode switches`.

---

### Task 7 [light]: Live-path contract suite, parity, live smoke harness and Phase 3 docs (P3-09, P3-10 harness)

**Files:** Create `tests/test_live_contract.py`, `tests/live/test_live_smoke.py`, `docs/verification/README.md`. Modify `pyproject.toml` (`[tool.pytest.ini_options] markers = ["live: real xAI calls; needs RUN_LIVE_TESTS=1"]`, `addopts` adds `-m "not live"`), `docs/PRD.md`, `docs/tickets/README.md`, `docs/tickets/P3-*.md` (statuses; P3-10 stays `blocked`), `README.md`.

**Interfaces — consumes:** everything above; `tests/fakes/xai_client.py`.

- Contract tests through `process_invoice(mode=live)` with the fake: happy path INV-1001 with one `lookup_inventory` tool call → `paid_mock`; malformed → repair (extraction) → success; timeout → retry → success; timeout ×2 → `failed` recoverable; runaway tool loop → `model_tool_loop_exceeded`; budget exhaustion → `model_budget_exhausted`; unauthorized tool request → `tool_rejected` audit event and the run continues; auth error → `model_auth_error`; rate limit then success; refusal → `model_refused`. Every `ModelErrorCode` value is produced by at least one test (assert over the enum).
- Parity: for every file in `data/invoices/`, a "reasonable" scripted fake (recommendation = offline simulator's, critique agrees, no proposals) in live mode gives the same final status as `tests/test_acceptance.py::CASES`.
- `tests/live/test_live_smoke.py` (`@pytest.mark.live`, skipped unless `RUN_LIVE_TESTS=1` and settings load): runs INV-1001, 1002, 1003, 1012, 1013, 1014, `valid_10000_01.json` and the four adversarial fixtures on fresh dbs; asserts business invariants only (status per P2-11 / `awaiting_human_approval` for 10,000.01; ≥ 1 tool call; critique recorded; no payment for blocked; `model_calls_used ≤ budget`); writes `docs/verification/live-<date>.md` (SDK version, model, per-invoice status, calls, latency, tool calls, token usage, divergences) — never keys or prompts. Plus an invalid-key run → `model_auth_error`, unpaid, recoverable.
- Docs: PRD Phase 3 exit boxes 2 and 3 ticked with test ids; box 1 left unticked with "pending user's xAI key (P3-10)"; P3-01 … P3-09 done/(complete); P3-10 `blocked`/(pending); carry-over rows for P3-01/P3-07/P3-08 struck or moved with reasons; README "Live mode" section (settings, readiness, `RUN_LIVE_TESTS=1 uv run pytest -m live`, cost note).

- [ ] Steps: tests → fix anything they reveal in the owning module → full suite (live tests skipped) + ruff → clean-clone run in the scratchpad → commit `test: live-path contract and parity suites; live smoke harness; close Phase 3 except P3-10`.
