"""FastAPI application: thin HTTP routes over the shared processing service.

Routes never decide policy or pay anything; they call ``service.process_invoice`` (in a
background worker), the review actions in ``review`` and the read helpers in ``queries``. One
process-wide lock serializes processing and review mutations.

Run it: ``uv run python -m invoice_processing.api`` (binds 127.0.0.1 unless told otherwise).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from invoice_processing import (
    idempotency,
    intake,
    queries,
    readiness,
    review,
    samples,
    service,
    uploads,
)
from invoice_processing.codes import (
    ExecutionMode,
    InvoiceStatus,
    ModelErrorCode,
    ReviewAction,
    ReviewRefusal,
    RunStatus,
)
from invoice_processing.limits import DEFAULT_LIMITS, Limits
from invoice_processing.observability import LOGGER_NAME, configure_events
from invoice_processing.reasoning import ProviderUnavailable, get_provider
from invoice_processing.schemas import (
    CorrectionRequest,
    FieldChange,
    ProcessingResult,
    ReviewerName,
    ReviewQueue,
    ReviewReason,
)
from invoice_processing.seed import SEED_ITEMS, seed_inventory
from invoice_processing.service import RetryRefused, process_invoice, retry_run
from invoice_processing.storage import (
    SCHEMA_VERSION,
    SchemaVersionError,
    connect,
    init_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VITE_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")  # trusted Host header names (DNS rebinding)
LOOPBACK_HOSTS = set(LOCAL_HOSTS)
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MAX_JSON_BODY_BYTES = 64 * 1024  # the largest JSON body (ten corrections) is a few KiB
RUNS_ENDPOINT = "POST /api/runs"
RETRY_ENDPOINT = "POST /api/runs/{run_id}/retry"
CORRECTIONS_ENDPOINT = "POST /api/invoices/{invoice_id}/corrections"
APPROVE_ENDPOINT = "POST /api/invoices/{invoice_id}/approve"
DECLINE_ENDPOINT = "POST /api/invoices/{invoice_id}/decline"
CORRECTED_ENDPOINT = "POST /api/invoices/{invoice_id}/corrected-submission"
REVIEW_TRIGGERS = queries.REVIEW_RUN_TRIGGERS
RUN_START_TIMEOUT_S = 120.0

# One lock for everything that mutates state through the service: processing runs and review
# actions, all executed on the one worker thread. Process-wide on purpose: the prototype is a
# single local operator.
PROCESSING_LOCK = threading.Lock()


@dataclass
class ApiSettings:
    db_path: Path = field(default_factory=lambda: Path("inventory.db"))
    uploads_dir: Path = field(default_factory=lambda: Path("uploads"))
    samples_dir: Path = field(default_factory=lambda: REPO_ROOT / "data" / "invoices")
    frontend_dist: Path = field(default_factory=lambda: REPO_ROOT / "frontend" / "dist")
    cors_origins: tuple[str, ...] = VITE_ORIGINS  # also the cross-origin POSTs accepted
    allowed_hosts: tuple[str, ...] = LOCAL_HOSTS  # tests add "testserver" (TestClient)
    evaluation_date: date | None = None  # workspace default; None means "today"
    limits: Limits = DEFAULT_LIMITS
    run_start_timeout_s: float = RUN_START_TIMEOUT_S


# ---------------------------------------------------------------------------- errors

_STATUS_BY_CODE = {
    "stale_version": 409,
    "action_not_allowed": 409,
    "provider_unavailable": 409,
    "validation_error": 422,
    "not_found": 404,
    "file_too_large": 413,
    "busy": 503,
    "source_unavailable": 409,
    # RetryRefused reasons (service.retry_run), returned as the error code itself
    "unknown_run": 404,
    "not_failed": 409,
    "not_recoverable": 409,
    "source_mismatch": 409,
    "not_current": 409,
    "already_paid": 409,
    "idempotency_key_reused": 422,
    "unsupported_media_type": 415,
    "forbidden_origin": 403,
    "body_too_large": 413,
}


class ApiError(Exception):
    """An error with the uniform body ``{code, message, details}``."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Any = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.status_code = status_code or _STATUS_BY_CODE.get(code, 400)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


_RETRY_MESSAGES = {
    "unknown_run": "There is no run with this id.",
    "not_failed": "Only a failed run can be retried.",
    "not_recoverable": "This failure would happen again; retrying will not fix it.",
    "source_mismatch": "The stored file no longer matches the run's original document.",
    "already_paid": "Another run already paid this invoice. No additional payment.",
    "not_current": "A later version replaced this one, so this run cannot be retried.",
}


def _error_response(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body = ErrorBody(code=code, message=message, details=details)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(queries.NotFound)
    async def _not_found(_: Request, exc: queries.NotFound) -> JSONResponse:
        return _error_response(404, exc.code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "loc": [str(p) for p in e.get("loc", ())],
                "message": e.get("msg", ""),
                "type": e["type"],
            }
            for e in exc.errors()
        ]
        return _error_response(422, "validation_error", "The request is not valid.", details)

    @app.exception_handler(intake.IntakeError)
    async def _intake(_: Request, exc: intake.IntakeError) -> JSONResponse:
        status = 413 if exc.code == "file_too_large" else 422
        return _error_response(status, exc.code, str(exc))

    @app.exception_handler(ProviderUnavailable)
    async def _provider(_: Request, exc: ProviderUnavailable) -> JSONResponse:
        return _error_response(409, "provider_unavailable", str(exc))

    @app.exception_handler(RetryRefused)
    async def _retry_refused(_: Request, exc: RetryRefused) -> JSONResponse:
        details = {"reason": exc.reason, "run_id": exc.run_id, "receipt_id": exc.receipt_id}
        return _error_response(
            _STATUS_BY_CODE.get(exc.reason, 409), exc.reason, _RETRY_MESSAGES[exc.reason], details
        )

    @app.exception_handler(SchemaVersionError)
    async def _schema(_: Request, exc: SchemaVersionError) -> JSONResponse:
        return _error_response(500, "database_unusable", str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # The envelope carries no exception text, traceback or path; the server log has them.
        return _error_response(
            500, "internal_error", "Something went wrong on the server. Nothing more is known."
        )


# ---------------------------------------------------------------------------- local web guard


class LocalRequestGuard:
    """Refuses cross-site writes from a browser on the same machine (pure ASGI middleware).

    For POST/PUT/PATCH/DELETE under /api:
    - an ``Origin`` header that is present must be the request's own origin or one of
      ``allowed_origins`` (the Vite dev server); anything else, including ``null``, is 403
      ``forbidden_origin``. Requests without Origin (curl, the CLI, TestClient) pass.
    - a JSON body is limited to ``MAX_JSON_BODY_BYTES`` (413 ``body_too_large``).

    The Host header is checked separately (TrustedHostMiddleware), so a same-origin match on a
    rebound DNS name never gets here."""

    def __init__(self, app: ASGIApp, allowed_origins: tuple[str, ...]) -> None:
        self.app = app
        self.allowed = {o.lower().rstrip("/") for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in STATE_CHANGING_METHODS
            or not scope["path"].startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        origin = headers.get("origin")
        if origin is not None:
            own = f"{scope.get('scheme', 'http')}://{headers.get('host', '')}".lower()
            if origin.lower().rstrip("/") not in self.allowed | {own}:
                await _error_response(
                    403,
                    "forbidden_origin",
                    "Requests that change data are accepted only from this application.",
                )(scope, receive, send)
                return
        if _media_type(headers.get("content-type")) == "application/json":
            body = await self._read_capped(receive, headers.get("content-length"))
            if body is None:
                await _error_response(
                    413,
                    "body_too_large",
                    f"The request body exceeds {MAX_JSON_BODY_BYTES // 1024} KiB.",
                )(scope, receive, send)
                return
            receive = _replay_body(body, receive)
        await self.app(scope, receive, send)

    @staticmethod
    async def _read_capped(receive: Receive, declared: str | None) -> bytes | None:
        if declared and declared.isdigit() and int(declared) > MAX_JSON_BODY_BYTES:
            return None
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return bytes(body)
            body += message.get("body", b"")
            if len(body) > MAX_JSON_BODY_BYTES:
                return None
            if not message.get("more_body", False):
                return bytes(body)


def _replay_body(body: bytes, receive: Receive) -> Receive:
    sent = False

    async def replay() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay


def _media_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _has_body(request: Request) -> bool:
    length = request.headers.get("content-length")
    return (length is not None and length != "0") or "transfer-encoding" in request.headers


def _unsupported(expected: str) -> ApiError:
    return ApiError("unsupported_media_type", f"The request body must be {expected}.")


def require_json(request: Request) -> None:
    """A JSON route: any body (or declared Content-Type) must be ``application/json``. A
    text/plain or form body is a CORS "simple" request a foreign page could send unseen."""
    media = _media_type(request.headers.get("content-type"))
    if (media or _has_body(request)) and media != "application/json":
        raise _unsupported("application/json")


def _require_multipart(request: Request) -> None:
    if _media_type(request.headers.get("content-type")) != "multipart/form-data":
        raise _unsupported("multipart/form-data")


RequireJson = Depends(require_json)


# ---------------------------------------------------------------------------- models


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Health(ApiModel):
    status: str


class ModeAvailability(ApiModel):
    available: bool
    reason: str | None = None


class Readiness(ApiModel):
    modes: dict[str, ModeAvailability]
    live_settings_present: bool
    inventory_seeded: bool
    database_path: str  # the database file name only
    schema_version: int
    live_model: str | None = None  # the configured XAI_MODEL when live settings are present


class RunRequest(ApiModel):
    """JSON body of ``POST /api/runs`` when submitting a bundled sample."""

    sample: str
    mode: ExecutionMode
    evaluation_date: date | None = None


class RetryRequest(ApiModel):
    """Optional JSON body of ``POST /api/runs/{run_id}/retry``.

    ``retry`` reprocesses in the failed run's own mode, linked by ``retry_of``.
    ``run_offline`` runs the same document offline as a separate, labeled simulation
    (``mode_switch_of``); only for live model failures, where the offline path can help.
    """

    action: Literal["retry", "run_offline"] = "retry"


class CorrectionBody(ApiModel):
    """JSON body of ``POST /api/invoices/{invoice_id}/corrections``: a ``CorrectionRequest``
    without ``invoice_id``, which is the path. ``expected_version`` is the version the
    reviewer saw; any other current version is refused as ``stale_version``."""

    expected_version: int = Field(ge=1)
    changes: list[FieldChange] = Field(min_length=1, max_length=10)
    reason: ReviewReason
    reviewer: ReviewerName


class ReviewDecisionBody(ApiModel):
    """JSON body of ``POST /api/invoices/{invoice_id}/approve`` and ``/decline``. The action
    applies to ``expected_version`` only."""

    expected_version: int = Field(ge=1)
    reason: ReviewReason
    reviewer: ReviewerName


class CorrectedSubmissionFields(ApiModel):
    """Form fields of ``POST /api/invoices/{invoice_id}/corrected-submission`` (with
    ``file``). ``mode`` defaults to the invoice's latest run's mode."""

    expected_version: int = Field(ge=1)
    reason: ReviewReason
    reviewer: ReviewerName
    mode: ExecutionMode | None = None
    evaluation_date: date | None = None


_CORRECTED_BODY_DOC = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file", "expected_version", "reason", "reviewer"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "expected_version": {"type": "integer", "minimum": 1},
                        "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
                        "reviewer": {"type": "string", "minLength": 1, "maxLength": 100},
                        "mode": {"type": "string", "enum": [m.value for m in ExecutionMode]},
                        "evaluation_date": {"type": "string", "format": "date"},
                    },
                }
            }
        },
    }
}


class RunAccepted(ApiModel):
    run_id: str
    status: RunStatus
    mode: ExecutionMode
    idempotent_replay: bool = False


# Inline schema whose enum refs point at the app's shared components (ExecutionMode is
# already there via RunAccepted); a bare model_json_schema() would leave dangling #/$defs refs.
_RUN_REQUEST_SCHEMA = {
    k: v
    for k, v in RunRequest.model_json_schema(ref_template="#/components/schemas/{model}").items()
    if k != "$defs"
}

_RUN_BODY_DOC = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": _RUN_REQUEST_SCHEMA},
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file", "mode"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "mode": {"type": "string", "enum": [m.value for m in ExecutionMode]},
                        "evaluation_date": {"type": "string", "format": "date"},
                    },
                }
            },
        },
    }
}


# ---------------------------------------------------------------------------- worker


RunJob = Callable[[Callable[[str], None]], object]


class RunWorker:
    """One background thread; every job runs under PROCESSING_LOCK with its own connection.

    The service reports the run id through its ``on_run_started`` hook as soon as the run
    row exists, so the HTTP response never depends on the event log."""

    def __init__(self, settings: ApiSettings) -> None:
        self._settings = settings
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="invoice-worker")

    def _events(self) -> logging.Logger:
        return logging.getLogger(LOGGER_NAME)

    def submit(
        self, path: Path, mode: ExecutionMode, evaluation_date: date, deadline: float | None = None
    ) -> str:
        """Queue one processing job and return its run id once the run row exists."""
        return self.run(
            lambda started: process_invoice(
                path,
                mode,
                self._settings.db_path,
                evaluation_date,
                events=self._events(),
                limits=self._settings.limits,
                on_run_started=started,
            ),
            deadline,
        )

    def submit_retry(
        self, run_id: str, path: Path | None, evaluation_date: date, deadline: float | None = None
    ) -> str:
        """Queue ``service.retry_run``; a RetryRefused or ProviderUnavailable is raised here."""
        return self.run(
            lambda started: retry_run(
                run_id,
                path,
                self._settings.db_path,
                evaluation_date,
                events=self._events(),
                limits=self._settings.limits,
                on_run_started=started,
            ),
            deadline,
        )

    def run(self, job_fn: RunJob, deadline: float | None = None) -> str:
        """Run ``job_fn(on_run_started)`` on the worker and return the run id it reports.

        A job that starts no run (a repeated approve of a paid version) reports the run id of
        the ``ProcessingResult`` it returns instead.

        The wait covers only the queue: another job holding PROCESSING_LOCK. Past ``deadline``
        (``time.monotonic()``; default ``run_start_timeout_s`` from now) the queued job is
        cancelled and the caller gets 503 busy."""
        started: Future[str] = Future()
        cancelled = threading.Event()

        def report(run_id: str) -> None:
            if not started.done():
                started.set_result(run_id)

        def job() -> None:
            with PROCESSING_LOCK:
                if cancelled.is_set():
                    return
                try:
                    out = job_fn(report)
                    if not started.done() and isinstance(out, ProcessingResult):
                        started.set_result(out.run_id)
                except Exception as exc:
                    if not started.done():
                        started.set_exception(exc)
                finally:
                    if not started.done():
                        started.set_exception(RuntimeError("processing ended before a run began"))

        if deadline is None:
            deadline = time.monotonic() + self._settings.run_start_timeout_s
        self._pool.submit(job)
        try:
            return started.result(timeout=max(0.0, deadline - time.monotonic()))
        except FutureTimeout:
            cancelled.set()
            raise _busy() from None

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------- app


def ensure_database(db_path: Path) -> None:
    """Create the schema and seed inventory. Idempotent; never resets data (same as the CLI)."""
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        init_schema(conn)
        seed_inventory(conn)
    finally:
        conn.close()


@contextmanager
def _db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _settings(request: Request) -> ApiSettings:
    return request.app.state.settings


def _live_status() -> readiness.LiveStatus:
    # Configuration only (Phase 3 readiness, without --ping): no SDK import, no socket.
    return readiness.live_status()


router = APIRouter(prefix="/api")

# Required on every POST: a custom header makes a browser preflight a cross-origin request.
IdempotencyKey = Annotated[str, Header(min_length=1, max_length=200)]


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok")


@router.get("/settings/readiness", response_model=Readiness)
def get_readiness(request: Request) -> Readiness:
    live = _live_status()
    with _db(request) as conn:
        stock = {r["item"] for r in conn.execute("SELECT item FROM inventory")}
    return Readiness(
        modes={
            "offline": ModeAvailability(available=True),
            "live": ModeAvailability(available=live.available, reason=live.reason),
        },
        live_settings_present=live.available,
        live_model=live.model,
        inventory_seeded=set(SEED_ITEMS) <= stock,
        database_path=Path(_settings(request).db_path).name,  # never the absolute path
        schema_version=SCHEMA_VERSION,
    )


@router.get("/samples", response_model=list[samples.Sample])
def list_samples(request: Request) -> list[samples.Sample]:
    return samples.list_samples(_settings(request).samples_dir)


def _accepted(conn: sqlite3.Connection, run_id: str, replay: bool) -> RunAccepted:
    row = conn.execute("SELECT status, mode FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return RunAccepted(
        run_id=run_id,
        status=RunStatus(row["status"]),
        mode=ExecutionMode(row["mode"]),
        idempotent_replay=replay,
    )


def _busy() -> ApiError:
    return ApiError("busy", "Another invoice is still processing. Try again shortly.")


def _deadline(request: Request) -> float:
    """One wait budget per request, shared by the idempotency lock and the worker queue."""
    return time.monotonic() + _settings(request).run_start_timeout_s


@contextmanager
def _locked(deadline: float) -> Iterator[None]:
    if not _idempotency_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
        raise _busy()
    try:
        yield
    finally:
        _idempotency_lock.release()


_KEY_REUSED = "This Idempotency-Key was already used for a different request."


def _replay(request: Request, key: str, fingerprint: str) -> RunAccepted | None:
    """The run stored for ``key`` on POST /api/runs, if the request is the same one.

    The stored record holds a fingerprint of (mode, evaluation date, sample name or upload
    sha256); a different request under the same key is refused (422). Records written before
    fingerprints existed replay as before."""
    with _db(request) as conn:
        stored = idempotency.lookup(conn, key, RUNS_ENDPOINT)
        if stored is None:
            return None
        saved = json.loads(stored)
        if saved.get("fingerprint", fingerprint) != fingerprint:
            raise ApiError("idempotency_key_reused", _KEY_REUSED)
        return _accepted(conn, saved["run_id"], replay=True)


def _run_fingerprint(
    mode: ExecutionMode, evaluation_date: date | None, sample: str | None, sha256: str | None
) -> str:
    return _fingerprint(
        {
            "mode": mode.value,
            "evaluation_date": None if evaluation_date is None else evaluation_date.isoformat(),
            "sample": sample,
            "sha256": sha256,
        }
    )


def _bad(message: str, field_name: str) -> ApiError:
    return ApiError(
        "validation_error",
        message,
        [{"loc": ["body", field_name], "message": message, "type": "value_error"}],
    )


def _parse_mode(raw: Any) -> ExecutionMode:
    try:
        return ExecutionMode(raw)
    except ValueError:
        raise _bad("mode must be 'offline' or 'live'.", "mode") from None


def _parse_date(raw: Any) -> date | None:
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise _bad("evaluation_date must be YYYY-MM-DD.", "evaluation_date") from None


_idempotency_lock = threading.Lock()


def _store_checked(settings: ApiSettings, upload: uploads.ParsedUpload) -> Path:
    """Store a parsed upload by hash and read it once with the intake limits (IntakeError
    for a bad file, which removes the stored copy again)."""
    if upload.temp_path is None or upload.sha256 is None:
        raise _bad("A file is required.", "file")
    stored = uploads.store_upload(
        upload.temp_path, upload.sha256, upload.filename, settings.uploads_dir
    )
    try:
        intake.read_source(stored, settings.limits)
    except intake.IntakeError:
        stored.unlink(missing_ok=True)
        try:
            stored.parent.rmdir()
        except OSError:
            pass
        raise
    return stored


async def _read_upload(request: Request) -> uploads.ParsedUpload:
    """The multipart body of an upload, size-limited like POST /api/runs."""
    settings = _settings(request)
    _require_multipart(request)
    try:
        return await uploads.read_multipart(
            request, settings.uploads_dir / ".tmp", settings.limits.max_bytes
        )
    except uploads.UploadTooLarge as exc:
        raise ApiError("file_too_large", str(exc)) from None
    except uploads.BadUpload as exc:
        raise _bad(str(exc), "file") from None


def _start_run(
    request: Request,
    *,
    mode: ExecutionMode,
    evaluation_date: date | None,
    key: str,
    sample: str | None = None,
    upload: uploads.ParsedUpload | None = None,
) -> RunAccepted:
    settings = _settings(request)
    deadline = _deadline(request)
    fingerprint = _run_fingerprint(
        mode, evaluation_date, sample, None if upload is None else upload.sha256
    )
    try:
        replay = _replay(request, key, fingerprint)  # before the lock: a replay never waits
        if replay is not None:
            return replay
        get_provider(mode)  # live-mode readiness error surfaces here, before any run exists
        if upload is not None:
            path = _store_checked(settings, upload)
        else:
            resolved = samples.resolve_sample(settings.samples_dir, sample or "")
            if resolved is None:
                raise _bad("sample must be the file name of a bundled sample.", "sample")
            path = resolved
            intake.read_source(path, settings.limits)
        when = evaluation_date or settings.evaluation_date or date.today()
        with _locked(deadline):
            replay = _replay(request, key, fingerprint)
            if replay is not None:
                return replay
            run_id = request.app.state.worker.submit(path, mode, when, deadline)
            with _db(request) as conn:
                accepted = _accepted(conn, run_id, replay=False)
                record = {"fingerprint": fingerprint, "run_id": run_id}
                idempotency.remember(conn, key, RUNS_ENDPOINT, json.dumps(record))
            return accepted
    finally:
        if upload is not None:
            uploads.discard(upload.temp_path)


@router.post(
    "/runs",
    status_code=202,
    response_model=RunAccepted,
    openapi_extra=_RUN_BODY_DOC,
    responses={
        409: {"model": ErrorBody},
        413: {"model": ErrorBody},
        422: {"model": ErrorBody},
    },
)
async def create_run(request: Request, idempotency_key: IdempotencyKey) -> RunAccepted:
    """Submit a bundled sample (``application/json``) or an upload (``multipart/form-data``);
    any other Content-Type is 415. The required Idempotency-Key replays the same run for the
    same request and refuses a different one (422 ``idempotency_key_reused``)."""
    media = _media_type(request.headers.get("content-type"))
    if media == "multipart/form-data":
        upload = await _read_upload(request)
        try:
            mode = _parse_mode(upload.fields.get("mode"))
            when = _parse_date(upload.fields.get("evaluation_date"))
        except ApiError:
            uploads.discard(upload.temp_path)
            raise
        return await run_in_threadpool(
            lambda: _start_run(
                request, mode=mode, evaluation_date=when, key=idempotency_key, upload=upload
            )
        )
    if media != "application/json":
        raise _unsupported("application/json or multipart/form-data")
    try:
        body = RunRequest.model_validate(await request.json())
    except (ValueError, ValidationError) as exc:
        details = (
            [
                {"loc": ["body", *map(str, e["loc"])], "message": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ]
            if isinstance(exc, ValidationError)
            else None
        )
        raise ApiError("validation_error", "The request body is not valid.", details) from None
    return await run_in_threadpool(
        lambda: _start_run(
            request,
            mode=body.mode,
            evaluation_date=body.evaluation_date,
            key=idempotency_key,
            sample=body.sample,
        )
    )


_OFFLINE_FIXABLE = frozenset(c.value for c in ModelErrorCode)


def _retry_source(request: Request, run_id: str) -> tuple[Path, ExecutionMode, date]:
    """The original file, mode and evaluation date of ``run_id``, or an error."""
    with _db(request) as conn:
        row = conn.execute(
            "SELECT source_id, mode, evaluation_date FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RetryRefused("unknown_run", run_id)
        record = queries.get_source_record(conn, row["source_id"])
    path = _locate_original(_settings(request), record)
    if path is None:
        raise ApiError(
            "source_unavailable",
            "The original file is no longer available, so this run cannot be reprocessed.",
            {"source_id": record.source_id},
        )
    when = (
        date.fromisoformat(row["evaluation_date"])
        if row["evaluation_date"]
        else _settings(request).evaluation_date or date.today()
    )
    return path, ExecutionMode(row["mode"]), when


def _run_trigger(request: Request, run_id: str) -> str | None:
    with _db(request) as conn:
        row = conn.execute("SELECT trigger FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return None if row is None else row["trigger"]


def _retry_replay(request: Request, key: str, endpoint: str) -> RunAccepted | None:
    with _db(request) as conn:
        stored = idempotency.lookup(conn, key, endpoint)
        return None if stored is None else _accepted(conn, json.loads(stored)["run_id"], True)


def _start_retry(request: Request, run_id: str, action: str, key: str) -> RunAccepted:
    endpoint = f"{RETRY_ENDPOINT}:{run_id}:{action}"
    settings = _settings(request)
    deadline = _deadline(request)
    replay = _retry_replay(request, key, endpoint)  # before the lock: a replay never waits
    if replay is not None:
        return replay
    path: Path | None
    trigger = _run_trigger(request, run_id)
    if trigger in queries.NO_OFFLINE_TRIGGERS and action != "retry":
        # A run started by a review action is retried in its own mode; a separate offline
        # run of the document would be a plain submission, discarding the review.
        raise ApiError(
            "not_recoverable",
            "A failed review run is retried in its own mode; running the document offline "
            "would discard the review action.",
            {"reason": "not_recoverable", "run_id": run_id, "receipt_id": None},
        )
    if trigger in REVIEW_TRIGGERS:
        # A correction or human-review run is retried on its own version from validation
        # (Decision 18): no file.
        path, when = None, settings.evaluation_date or date.today()  # the run keeps its own
    else:
        path, _mode, when = _retry_source(request, run_id)
    with _locked(deadline):
        replay = _retry_replay(request, key, endpoint)
        if replay is not None:
            return replay
        worker: RunWorker = request.app.state.worker
        if action == "retry":
            new_run = worker.submit_retry(run_id, path, when, deadline)
        else:
            # Same refusals as a retry (unknown, not failed, wrong file, already paid), and
            # only a live model failure: offline cannot fix a deterministic or offline error.
            assert path is not None  # a review run never runs offline (above)
            original = service.check_retry(run_id, path, settings.db_path, settings.limits)
            if original.mode is not ExecutionMode.live or original.error_code not in (
                _OFFLINE_FIXABLE
            ):
                raise RetryRefused("not_recoverable", run_id)
            new_run = worker.submit(path, ExecutionMode.offline, when, deadline)
        with _db(request) as conn:
            accepted = _accepted(conn, new_run, replay=False)
            idempotency.remember(conn, key, endpoint, accepted.model_dump_json())
        return accepted


@router.post(
    "/runs/{run_id}/retry",
    status_code=202,
    response_model=RunAccepted,
    responses={
        404: {"model": ErrorBody},
        409: {"model": ErrorBody},
        422: {"model": ErrorBody},
        503: {"model": ErrorBody},
    },
)
def create_retry(
    run_id: str,
    request: Request,
    idempotency_key: IdempotencyKey,
    body: RetryRequest | None = None,
    _json: None = RequireJson,
) -> RunAccepted:
    """Explicitly retry a recoverable failed run (P3-08). Creates a new linked run; never
    resumes the failed one. Refusals use the RetryRefused reason as the error code."""
    action = (body or RetryRequest()).action
    return _start_retry(request, run_id, action, idempotency_key)


@router.get("/runs/{run_id}", response_model=queries.RunView)
def get_run(run_id: str, request: Request) -> queries.RunView:
    with _db(request) as conn:
        return queries.get_run(conn, run_id)


@router.get("/overview", response_model=queries.Overview)
def overview(request: Request) -> queries.Overview:
    with _db(request) as conn:
        return queries.overview(conn)


@router.get("/invoices", response_model=queries.InvoiceList)
def list_invoices(
    request: Request,
    status: InvoiceStatus | None = None,
    mode: ExecutionMode | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> queries.InvoiceList:
    with _db(request) as conn:
        return queries.list_invoices(conn, status=status, mode=mode, q=q, page=page)


def _invoice_detail(request: Request, invoice_id: str) -> queries.InvoiceDetail:
    """``GET /api/invoices/{id}``: the stored record plus its current review actions."""
    with _db(request) as conn:
        detail = queries.get_invoice(conn, invoice_id)
    actions = review.allowed_actions(invoice_id, db_path=_settings(request).db_path)
    return detail.model_copy(update={"review_actions": actions})


@router.get("/invoices/{invoice_id}", response_model=queries.InvoiceDetail)
def get_invoice(invoice_id: str, request: Request) -> queries.InvoiceDetail:
    return _invoice_detail(request, invoice_id)


@router.get(
    "/invoices/{invoice_id}/result.json",
    response_model=queries.ProcessingResult,
)
def invoice_result(invoice_id: str, request: Request) -> Response:
    with _db(request) as conn:
        queries.get_invoice(conn, invoice_id)  # 404 for an unknown invoice
        run_id = queries.latest_business_run_id(conn, invoice_id)
        if run_id is None:
            raise queries.NotFound("result_not_found", "This invoice has no processing result.")
        result = queries.build_result(conn, run_id)
    return Response(
        content=queries.dump_json(result),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="result-{invoice_id}.json"'},
    )


# ---------------------------------------------------------------------------- review actions
#
# Every review action (corrections, approve, decline, corrected submissions) goes through
# `_review_action`, which follows POST /api/runs: the action runs on the worker under
# PROCESSING_LOCK and the response (202 RunAccepted) is sent as soon as its run is committed,
# via the service's `on_run_started` hook; the client follows GET /api/runs/{run_id}.
# An Idempotency-Key is required; a repeated key replays the same run (`idempotent_replay`).
# `ReviewRefused` is raised before any run exists and maps to:
#   stale_version, action_not_allowed, already_paid -> 409, details {current, invoice}
#   unknown_invoice -> 404; any other refusal -> 422, details {current}
# Only accepted actions are stored: a refusal writes nothing, so a resend re-checks.

_REVIEW_CONFLICTS = frozenset(
    {ReviewRefusal.stale_version, ReviewRefusal.action_not_allowed, ReviewRefusal.already_paid}
)


def _refusal_error(request: Request, exc: review.ReviewRefused, invoice_id: str) -> ApiError:
    details: dict[str, Any] = {
        "current": None if exc.current is None else exc.current.model_dump(mode="json")
    }
    if exc.code is ReviewRefusal.unknown_invoice:
        status = 404
    elif exc.code in _REVIEW_CONFLICTS:
        status = 409
        # The current record, so the UI can refresh in place without another request.
        details["invoice"] = _invoice_detail(request, invoice_id).model_dump(mode="json")
    else:
        status = 422
    return ApiError(exc.code.value, exc.message, details, status_code=status)


def _validation_error(exc: ValidationError) -> ApiError:
    details = [
        {"loc": ["body", *map(str, e["loc"])], "message": e["msg"], "type": e["type"]}
        for e in exc.errors()
    ]
    return ApiError("validation_error", "The request body is not valid.", details)


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


ReviewCall = Callable[[Callable[[str], None]], ProcessingResult]


def _review_action(
    request: Request,
    *,
    endpoint: str,
    invoice_id: str,
    key: str,
    payload: dict[str, Any],
    act: ReviewCall,
) -> JSONResponse:
    """Run ``act(on_run_started)`` on the worker, idempotently per (key, endpoint, invoice).

    202 once the action's run is committed. 200 when the action started no run: a repeated
    approve of the paid version answers with the paying run (``idempotent_replay``). A
    repeated key with the same payload replays the stored run; with another payload it is
    refused (422 ``idempotency_key_reused``)."""
    scope = f"{endpoint}:{invoice_id}"
    fingerprint = _fingerprint(payload)
    deadline = _deadline(request)

    def stored_replay() -> JSONResponse | None:
        with _db(request) as conn:
            stored = idempotency.lookup(conn, key, scope)
            if stored is None:
                return None
            saved = json.loads(stored)
            if saved["fingerprint"] != fingerprint:
                raise ApiError("idempotency_key_reused", _KEY_REUSED)
            replay = _accepted(conn, saved["run_id"], replay=True)
            return JSONResponse(replay.model_dump(mode="json"), status_code=saved["status"])

    early = stored_replay()  # before the lock: a replay never waits behind other work
    if early is not None:
        return early
    with _locked(deadline):
        again = stored_replay()
        if again is not None:
            return again
        started: list[str] = []

        def job(report: Callable[[str], None]) -> ProcessingResult:
            def hook(run_id: str) -> None:
                started.append(run_id)
                report(run_id)

            return act(hook)

        try:
            run_id = request.app.state.worker.run(job, deadline)
        except review.ReviewRefused as exc:
            raise _refusal_error(request, exc, invoice_id) from None
        status = 202 if started else 200
        with _db(request) as conn:
            accepted = _accepted(conn, run_id, replay=not started)
            record = {"fingerprint": fingerprint, "run_id": run_id, "status": status}
            idempotency.remember(conn, key, scope, json.dumps(record))
    return JSONResponse(accepted.model_dump(mode="json"), status_code=status)


_REVIEW_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "model": RunAccepted,
        "description": "No new run: a repeated approve of the paid version answers with the "
        "paying run (`idempotent_replay`: true).",
    },
    404: {"model": ErrorBody, "description": "Unknown invoice (`unknown_invoice`)."},
    409: {
        "model": ErrorBody,
        "description": "`stale_version`, `action_not_allowed`, `already_paid` or "
        "`provider_unavailable`. Review refusals carry `details.current` (AllowedActions) "
        "and `details.invoice` (the current invoice detail).",
    },
    422: {
        "model": ErrorBody,
        "description": "A review refusal code (e.g. `correction_not_in_source`) with "
        "`details.current`, `validation_error`, or `idempotency_key_reused`.",
    },
    503: {"model": ErrorBody, "description": "`busy`: another invoice is processing."},
}


def _events_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


@router.post(
    "/invoices/{invoice_id}/corrections",
    status_code=202,
    response_model=RunAccepted,
    responses=_REVIEW_RESPONSES,
)
def create_correction(
    invoice_id: str,
    body: CorrectionBody,
    request: Request,
    idempotency_key: IdempotencyKey,
    _json: None = RequireJson,
) -> Response:
    """Correct extracted fields with source evidence (``review.submit_correction``): a new
    version is recorded and revalidated by a new run, whose id is returned at once."""
    try:
        correction = CorrectionRequest(invoice_id=invoice_id, **body.model_dump())
    except ValidationError as exc:
        raise _validation_error(exc) from None
    db_path = _settings(request).db_path
    return _review_action(
        request,
        endpoint=CORRECTIONS_ENDPOINT,
        invoice_id=invoice_id,
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        act=lambda started: review.submit_correction(
            correction, db_path=db_path, events=_events_logger(), on_run_started=started
        ),
    )


def _decision_route(endpoint: str, fn: Callable[..., ProcessingResult]):
    def route(
        invoice_id: str,
        body: ReviewDecisionBody,
        request: Request,
        idempotency_key: IdempotencyKey,
        _json: None = RequireJson,
    ) -> Response:
        db_path = _settings(request).db_path
        return _review_action(
            request,
            endpoint=endpoint,
            invoice_id=invoice_id,
            key=idempotency_key,
            payload=body.model_dump(mode="json"),
            act=lambda started: fn(
                invoice_id,
                body.expected_version,
                body.reviewer,
                body.reason,
                db_path=db_path,
                events=_events_logger(),
                on_run_started=started,
            ),
        )

    return route


router.add_api_route(
    "/invoices/{invoice_id}/approve",
    _decision_route(APPROVE_ENDPOINT, review.approve),
    methods=["POST"],
    status_code=202,
    response_model=RunAccepted,
    responses=_REVIEW_RESPONSES,
    name="approve_invoice",
    summary="Approve Invoice",
    description="Approve mock payment of `expected_version` (``review.approve``). The "
    "human-review run revalidates and pays only if the gate approves.",
)
router.add_api_route(
    "/invoices/{invoice_id}/decline",
    _decision_route(DECLINE_ENDPOINT, review.decline),
    methods=["POST"],
    status_code=202,
    response_model=RunAccepted,
    responses=_REVIEW_RESPONSES,
    name="decline_invoice",
    summary="Decline Invoice",
    description="Decline `expected_version` (``review.decline``): the human-review run "
    "rejects it at the gate; no payment.",
)


@router.post(
    "/invoices/{invoice_id}/corrected-submission",
    status_code=202,
    response_model=RunAccepted,
    responses={**_REVIEW_RESPONSES, 413: {"model": ErrorBody}},
    openapi_extra=_CORRECTED_BODY_DOC,
)
async def create_corrected_submission(
    invoice_id: str, request: Request, idempotency_key: IdempotencyKey
) -> Response:
    """Submit a corrected invoice from the vendor (``review.submit_corrected_invoice``): the
    file is processed as a new version that supersedes the earlier ones. The upload is checked
    like ``POST /api/runs``. ``expected_version`` is the version the reviewer saw. A file with
    another vendor or invoice number fails its run with ``corrected_identity_mismatch``."""
    upload = await _read_upload(request)
    try:
        try:
            fields = CorrectedSubmissionFields.model_validate(
                {k: v for k, v in upload.fields.items() if v != ""}
            )
        except ValidationError as exc:
            raise _validation_error(exc) from None
        return await run_in_threadpool(
            _corrected_submission, request, invoice_id, fields, upload, idempotency_key
        )
    finally:
        uploads.discard(upload.temp_path)


def _corrected_submission(
    request: Request,
    invoice_id: str,
    fields: CorrectedSubmissionFields,
    upload: uploads.ParsedUpload,
    key: str,
) -> Response:
    settings = _settings(request)
    path = _store_checked(settings, upload)
    when = fields.evaluation_date or settings.evaluation_date or date.today()
    db_path = settings.db_path

    def act(started: Callable[[str], None]) -> ProcessingResult:
        # The service has no expected version: the API binds the action to the one shown.
        current = review.allowed_actions(invoice_id, db_path=db_path)
        if current.current_version != fields.expected_version:
            paid = current.refused.get(ReviewAction.submit_corrected) is ReviewRefusal.already_paid
            code = ReviewRefusal.already_paid if paid else ReviewRefusal.stale_version
            raise review.ReviewRefused(code, review.MESSAGES[code], current)
        return review.submit_corrected_invoice(
            invoice_id,
            path,
            fields.reason,
            fields.reviewer,
            db_path=db_path,
            evaluation_date=when,
            mode=fields.mode,
            events=_events_logger(),
            limits=settings.limits,
            on_run_started=started,
        )

    payload = {**fields.model_dump(mode="json"), "sha256": upload.sha256}
    return _review_action(
        request,
        endpoint=CORRECTED_ENDPOINT,
        invoice_id=invoice_id,
        key=key,
        payload=payload,
        act=act,
    )


@router.get("/review-queue", response_model=ReviewQueue)
def review_queue(request: Request) -> ReviewQueue:
    """Invoices waiting on a person, in three groups (``review.list_queue``); each item
    carries its AllowedActions."""
    return review.list_queue(db_path=_settings(request).db_path)


def _locate_original(settings: ApiSettings, record: queries.SourceRecord) -> Path | None:
    """The original bytes of a source: an upload stored by hash, or a bundled sample."""
    candidates: list[Path] = []
    stored = settings.uploads_dir / record.content_hash
    if stored.is_dir():
        candidates.extend(sorted(p for p in stored.iterdir() if p.is_file()))
    candidates.append(settings.samples_dir / Path(record.original_name).name)
    for path in candidates:
        try:
            if (
                path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == record.content_hash
            ):
                return path
        except OSError:
            continue
    return None


@router.get("/sources/{source_id}/content", response_model=queries.SourceContent)
def source_content(source_id: str, request: Request) -> queries.SourceContent:
    settings = _settings(request)
    with _db(request) as conn:
        record = queries.get_source_record(conn, source_id)
    original = _locate_original(settings, record)
    raw_text = None
    if original is not None and record.format.value != "pdf":
        raw_text = original.read_text(encoding="utf-8", errors="replace").removeprefix("﻿")
    return queries.source_content(record, raw_text, has_original=original is not None)


# The original bytes are untrusted (an uploaded .xml can be XHTML with a script). Every
# response is sandboxed with no sources allowed and never sniffed; only a PDF is shown inline
# (the UI embeds it); any other format is inert text, downloaded.
ORIGINAL_CSP = "sandbox; default-src 'none'"


@router.get("/sources/{source_id}/original", response_class=FileResponse)
def source_original(source_id: str, request: Request) -> FileResponse:
    with _db(request) as conn:
        record = queries.get_source_record(conn, source_id)
    original = _locate_original(_settings(request), record)
    if original is None:
        raise queries.NotFound("original_not_found", "The original file is no longer available.")
    headers = {"Content-Security-Policy": ORIGINAL_CSP, "X-Content-Type-Options": "nosniff"}
    if record.format.value == "pdf":
        return FileResponse(
            original,
            media_type="application/pdf",
            headers={**headers, "Content-Disposition": "inline"},
        )
    name = uploads.safe_filename(record.original_name)
    return FileResponse(
        original,
        media_type="text/plain; charset=utf-8",
        headers={**headers, "Content-Disposition": f'attachment; filename="{name}"'},
    )


class SpaStaticFiles(StaticFiles):
    """The built UI. Client-side routes (/invoices/x, /runs/x) fall back to index.html so a
    browser refresh or deep link works; unknown /api paths and missing assets stay 404."""

    async def get_response(self, path: str, scope: Any) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            last = path.rsplit("/", 1)[-1]
            if exc.status_code != 404 or path.split("/", 1)[0] == "api" or "." in last:
                raise
            return await super().get_response("index.html", scope)


def _host_patterns(hosts: tuple[str, ...]) -> list[str]:
    """Starlette compares the Host name with IPv6 literals still bracketed ("[::1]")."""
    return [f"[{h}]" if ":" in h and not h.startswith("[") else h for h in hosts]


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or ApiSettings()
    ensure_database(Path(settings.db_path))
    settings.uploads_dir = Path(settings.uploads_dir)
    worker = RunWorker(settings)

    @asynccontextmanager
    async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        worker.shutdown()

    app = FastAPI(title="Invoice Processing API", version="0.1.0", lifespan=_lifespan)
    app.state.settings = settings
    app.state.worker = worker
    # Outermost last: Host check, then the Origin/body guard, then CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )
    app.add_middleware(LocalRequestGuard, allowed_origins=tuple(settings.cors_origins))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_host_patterns(settings.allowed_hosts))
    _install_error_handlers(app)
    app.include_router(router)
    dist = Path(settings.frontend_dist)
    if dist.is_dir():
        app.mount("/", SpaStaticFiles(directory=dist, html=True), name="frontend")
    return app


# ---------------------------------------------------------------------------- command line


def check_bind_host(host: str, allow_public: bool) -> None:
    if host not in LOOPBACK_HOSTS and not allow_public:
        raise ValueError(
            f"refusing to bind to {host!r}: the API has no authentication. "
            "Pass --allow-public-bind to override."
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Serve the invoice-processing API (and built UI).")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--db", default="inventory.db", help="SQLite database path")
    p.add_argument("--allow-public-bind", action="store_true", help="allow non-loopback hosts")
    args = p.parse_args(argv)
    try:
        check_bind_host(args.host, args.allow_public_bind)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    import uvicorn

    configure_events(Path("output/events.jsonl"))
    app = create_app(ApiSettings(db_path=Path(args.db)))
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
