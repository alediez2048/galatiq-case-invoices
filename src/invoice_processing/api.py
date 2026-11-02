"""FastAPI application: thin HTTP routes over the shared processing service.

Routes never decide policy or pay anything; they call ``service.process_invoice`` (in a
background worker) and the read helpers in ``queries``. One process-wide lock serializes
processing (and, later, review mutations).

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
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from invoice_processing import idempotency, intake, queries, readiness, samples, service, uploads
from invoice_processing.codes import ExecutionMode, InvoiceStatus, ModelErrorCode, RunStatus
from invoice_processing.limits import DEFAULT_LIMITS, Limits
from invoice_processing.observability import LOGGER_NAME, configure_events
from invoice_processing.reasoning import ProviderUnavailable, get_provider
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
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
RUNS_ENDPOINT = "POST /api/runs"
RETRY_ENDPOINT = "POST /api/runs/{run_id}/retry"
RUN_START_TIMEOUT_S = 120.0

# One lock for everything that mutates state through the service: processing today, review
# actions (P5-04) later. Process-wide on purpose: the prototype is a single local operator.
PROCESSING_LOCK = threading.Lock()


@dataclass
class ApiSettings:
    db_path: Path = field(default_factory=lambda: Path("inventory.db"))
    uploads_dir: Path = field(default_factory=lambda: Path("uploads"))
    samples_dir: Path = field(default_factory=lambda: REPO_ROOT / "data" / "invoices")
    frontend_dist: Path = field(default_factory=lambda: REPO_ROOT / "frontend" / "dist")
    cors_origins: tuple[str, ...] = VITE_ORIGINS
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
    "already_paid": 409,
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
    database_path: str
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

    def submit(self, path: Path, mode: ExecutionMode, evaluation_date: date) -> str:
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
            )
        )

    def submit_retry(self, run_id: str, path: Path, evaluation_date: date) -> str:
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
            )
        )

    def run(self, job_fn: RunJob) -> str:
        """Run ``job_fn(on_run_started)`` on the worker and return the run id it reports.

        The wait covers only the queue: another job holding PROCESSING_LOCK. Past
        ``run_start_timeout_s`` the queued job is cancelled and the caller gets 503 busy."""
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
                    job_fn(report)
                except Exception as exc:
                    if not started.done():
                        started.set_exception(exc)
                finally:
                    if not started.done():
                        started.set_exception(RuntimeError("processing ended before a run began"))

        self._pool.submit(job)
        try:
            return started.result(timeout=self._settings.run_start_timeout_s)
        except FutureTimeout:
            cancelled.set()
            raise ApiError(
                "busy", "Another invoice is still processing. Try again shortly."
            ) from None

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
        database_path=str(_settings(request).db_path),
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


def _replay(request: Request, key: str | None) -> RunAccepted | None:
    if not key:
        return None
    with _db(request) as conn:
        stored = idempotency.lookup(conn, key, RUNS_ENDPOINT)
        if stored is None:
            return None
        return _accepted(conn, json.loads(stored)["run_id"], replay=True)


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


def _start_run(
    request: Request,
    *,
    mode: ExecutionMode,
    evaluation_date: date | None,
    key: str | None,
    sample: str | None = None,
    upload: uploads.ParsedUpload | None = None,
) -> RunAccepted:
    settings = _settings(request)
    stored_path: Path | None = None
    try:
        get_provider(mode)  # live-mode readiness error surfaces here, before any run exists
        if upload is not None:
            if upload.temp_path is None or upload.sha256 is None:
                raise _bad("A file is required.", "file")
            stored_path = uploads.store_upload(
                upload.temp_path, upload.sha256, upload.filename, settings.uploads_dir
            )
            path = stored_path
        else:
            resolved = samples.resolve_sample(settings.samples_dir, sample or "")
            if resolved is None:
                raise _bad("sample must be the file name of a bundled sample.", "sample")
            path = resolved
        try:
            intake.read_source(path, settings.limits)
        except intake.IntakeError:
            if stored_path is not None:
                stored_path.unlink(missing_ok=True)
                try:
                    stored_path.parent.rmdir()
                except OSError:
                    pass
            raise
        when = evaluation_date or settings.evaluation_date or date.today()
        with _idempotency_lock:
            replay = _replay(request, key)
            if replay is not None:
                return replay
            run_id = request.app.state.worker.submit(path, mode, when)
            with _db(request) as conn:
                accepted = _accepted(conn, run_id, replay=False)
                if key:
                    idempotency.remember(conn, key, RUNS_ENDPOINT, accepted.model_dump_json())
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
async def create_run(
    request: Request,
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None,
) -> RunAccepted:
    replay = await run_in_threadpool(_replay, request, idempotency_key)
    if replay is not None:
        return replay
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        settings = _settings(request)
        try:
            upload = await uploads.read_multipart(
                request, settings.uploads_dir / ".tmp", settings.limits.max_bytes
            )
        except uploads.UploadTooLarge as exc:
            raise ApiError("file_too_large", str(exc)) from None
        except uploads.BadUpload as exc:
            raise _bad(str(exc), "file") from None
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


def _start_retry(request: Request, run_id: str, action: str, key: str | None) -> RunAccepted:
    endpoint = f"{RETRY_ENDPOINT}:{run_id}:{action}"
    path, mode, when = _retry_source(request, run_id)
    settings = _settings(request)
    with _idempotency_lock:
        if key:
            with _db(request) as conn:
                stored = idempotency.lookup(conn, key, endpoint)
                if stored is not None:
                    return _accepted(conn, json.loads(stored)["run_id"], replay=True)
        worker: RunWorker = request.app.state.worker
        if action == "retry":
            new_run = worker.submit_retry(run_id, path, when)
        else:
            # Same refusals as a retry (unknown, not failed, wrong file, already paid), and
            # only a live model failure: offline cannot fix a deterministic or offline error.
            original = service.check_retry(run_id, path, settings.db_path, settings.limits)
            if original.mode is not ExecutionMode.live or original.error_code not in (
                _OFFLINE_FIXABLE
            ):
                raise RetryRefused("not_recoverable", run_id)
            new_run = worker.submit(path, ExecutionMode.offline, when)
        with _db(request) as conn:
            accepted = _accepted(conn, new_run, replay=False)
            if key:
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
    body: RetryRequest | None = None,
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None,
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


@router.get("/invoices/{invoice_id}", response_model=queries.InvoiceDetail)
def get_invoice(invoice_id: str, request: Request) -> queries.InvoiceDetail:
    with _db(request) as conn:
        return queries.get_invoice(conn, invoice_id)


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


# TODO(P4-05): GET /api/review-queue wraps the review queue once the review service exists.


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


_MEDIA = {
    "pdf": "application/pdf",
    "json": "application/json",
    "xml": "application/xml",
    "csv": "text/csv",
    "txt": "text/plain",
}


@router.get("/sources/{source_id}/original", response_class=FileResponse)
def source_original(source_id: str, request: Request) -> FileResponse:
    with _db(request) as conn:
        record = queries.get_source_record(conn, source_id)
    original = _locate_original(_settings(request), record)
    if original is None:
        raise queries.NotFound("original_not_found", "The original file is no longer available.")
    return FileResponse(
        original,
        media_type=_MEDIA.get(record.format.value, "application/octet-stream"),
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )
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
