# P5-01 — FastAPI application skeleton

Phase: 5 · Status: todo · Depends on: P1-07, P4-05 · Requirements: P12

## Context

FastAPI handlers and the CLI call the same Python service; the backend, not the browser, owns policy and payment authorization ([system design — interface](../systemsdesign.md#interface)). Single local operator; processing is serialized ([constraints — operational bounds](../contraints.md#proposed-operational-bounds)).

## Scope

- Add `fastapi`, `uvicorn`, `python-multipart`; refresh the lock.
- `src/invoice_processing/api.py`: app factory `create_app(settings)`, routes under `/api`, typed request/response models reusing `schemas.py`.
- Bind to `127.0.0.1` by default; CORS allows only the local Vite dev origin.
- Uniform error body `{code, message, details}` mapping service errors: `stale_version` → 409, `action_not_allowed` → 409, validation → 422, not found → 404, limits → 413.
- A single process-wide lock serializes processing and review mutations.
- Startup: ensure schema and run the idempotent seed (mockup allows automatic seeding; never resets data).
- `GET /api/health` and `GET /api/settings/readiness` (mode availability, live settings present yes/no, inventory seeded, DB path). Never returns secret values.
- Export the OpenAPI schema to `frontend/src/api/openapi.json` via a script for the typed client (P5-05).
- `python -m invoice_processing.api` (or `uvicorn` command) documented in `docs/development.md`.

## Acceptance criteria

- [ ] `TestClient` tests for health, readiness, and the error mapping.
- [ ] Readiness with no live key reports live unavailable without exposing anything else.
- [ ] Server refuses to bind to `0.0.0.0` unless an explicit flag is given.
- [ ] No route imports policy or payment logic directly; all go through `service.py` / `review.py` (import test).
