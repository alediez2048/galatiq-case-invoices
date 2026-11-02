"""Structured JSONL event logging and result output."""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from invoice_processing.ledger import redact
from invoice_processing.money import format_money
from invoice_processing.schemas import ProcessingResult

EVENT_FIELDS = (
    "ts",
    "run_id",
    "stage",
    "event",
    "status",
    "mode",
    "source_hash",
    "duration_ms",
    "codes",
)

LOGGER_NAME = "invoice_processing.events"


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = redact(getattr(record, "event_data", {}) or {})
        ts = datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z")
        return json.dumps({"ts": ts, **data}, default=str)


def configure_events(path: Path | None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    handler: logging.Handler
    if path is not None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLineFormatter())
    logger.addHandler(handler)
    return logger


def log_event(
    logger: logging.Logger,
    *,
    run_id: str | None,
    stage: str,
    event: str,
    **fields: Any,
) -> None:
    data = {"run_id": run_id, "stage": stage, "event": event, **fields}
    logger.info(event, extra={"event_data": data})


@contextmanager
def stage_timer() -> Iterator[dict[str, Any]]:
    timing: dict[str, Any] = {}
    start = time.perf_counter()
    try:
        yield timing
    finally:
        timing["duration_ms"] = int((time.perf_counter() - start) * 1000)


def write_result(result: ProcessingResult, out: Path | TextIO | None = None) -> None:
    text = result.model_dump_json(indent=2) + "\n"
    if isinstance(out, Path):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        return
    stream = out if out is not None else sys.stdout
    stream.write(text)


def format_summary(result: ProcessingResult) -> str:
    parts = [f"status={result.status.value}", f"run={result.run_id}"]
    if result.invoice_id:
        parts.append(f"invoice={result.invoice_id}")
    if result.receipt:
        parts.append(f"paid={format_money(result.receipt.amount, result.receipt.currency)}")
    if result.errors:
        parts.append(f"errors={len(result.errors)}")
        parts.append(f"error={result.errors[0]}")
    if result.error_message:
        parts.append(f'reason="{result.error_message}"')
    return " ".join(parts)
