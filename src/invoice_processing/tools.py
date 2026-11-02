"""Whitelisted, read-only tools the model may call, and the dispatcher that guards them.

No tool writes, pays or changes policy: handlers get a `ReadOnlyConnection` that only runs
SELECT statements. The dispatcher refuses (never raises) unknown tools, unauthorized agents
and invalid arguments, and records every call as an audit event without the excerpt text.
"""

import csv
import io
import json
import logging
import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Annotated, Any
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from invoice_processing import ledger, storage
from invoice_processing.codes import Severity
from invoice_processing.parsers.text import LABELS
from invoice_processing.schemas import NormalizedInvoice
from invoice_processing.validation import reconcile_totals

_log = logging.getLogger(__name__)

MAX_ITEMS = 200
_PAGE_BREAK = "\n\f\n"  # joins PDF pages in the extracted text (see parsers/pdf.py)


class ReadOnlyConnection:
    """Exposes `execute` for SELECT statements only; anything else is refused."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        if not sql.lstrip().upper().startswith("SELECT"):
            raise PermissionError("read-only connection: only SELECT statements are allowed")
        return self._conn.execute(sql, parameters)

    @contextmanager
    def query_only(self) -> Iterator[None]:
        """Defence in depth while a handler runs: SQLite itself refuses writes.

        The wrapped connection is the run's writable one (an in-memory test database has no
        second connection to open), so the pragma is switched on only for the handler's
        duration and always switched back; handlers run synchronously, so no ledger write
        can happen in between. Already-on (nested) stays on.
        """
        if self._conn.execute("PRAGMA query_only").fetchone()[0]:
            yield
            return
        self._conn.execute("PRAGMA query_only = ON")
        try:
            yield
        finally:
            self._conn.execute("PRAGMA query_only = OFF")


@dataclass(frozen=True)
class ToolContext:
    conn: ReadOnlyConnection
    run_id: str
    invoice: NormalizedInvoice | None = None
    invoice_id: str | None = None
    version_id: str | None = None
    source_text: str | None = None  # decoded TXT/JSON/CSV/XML bytes, or extracted PDF text
    excerpt_chars: int = 4000  # set by the Dispatcher from its argument


class ToolRejected(Exception):
    """A handler's refusal (for example an unknown location); reported, not an error."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], dict]
    allowed_agents: frozenset[str]

    def json_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class LookupInventoryArgs(_Args):
    items: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=MAX_ITEMS
    )


class GetFindingsArgs(_Args):
    severity: Severity | None = None


class SourceExcerptArgs(_Args):
    location: str = Field(min_length=1, max_length=200)


def _lookup_inventory(ctx: ToolContext, args: LookupInventoryArgs) -> dict:
    return {"stock": storage.get_stock(ctx.conn, args.items)}  # type: ignore[arg-type]


def _recompute_totals(ctx: ToolContext, args: NoArgs) -> dict:
    if ctx.invoice is None:
        raise ToolRejected("no_invoice")
    computed, findings = reconcile_totals(ctx.invoice)
    return {
        "computed": computed.model_dump(mode="json"),
        "stated": ctx.invoice.stated.model_dump(mode="json"),
        "finding_codes": [f.code.value for f in findings],
    }


def _get_findings(ctx: ToolContext, args: GetFindingsArgs) -> dict:
    return {"findings": ledger.list_findings(ctx.conn, ctx.run_id, args.severity)}  # type: ignore[arg-type]


def _lookup_prior_invoice(ctx: ToolContext, args: NoArgs) -> dict:
    if ctx.invoice_id is None:
        return {"known": False}
    history = ledger.invoice_history(ctx.conn, ctx.invoice_id, ctx.run_id)  # type: ignore[arg-type]
    return {"known": True, **history}


def _list_item_aliases(ctx: ToolContext, args: NoArgs) -> dict:
    return {
        "known_items": storage.inventory_items(ctx.conn),  # type: ignore[arg-type]
        "item_rules": [
            "item_spacing: whitespace inside a name is removed when that matches a known item",
            "item_qualifier: a trailing '(qualifier)' is moved to the line note",
        ],
        "label_spellings": {field: list(names) for field, names in LABELS.items()},
    }


def _text_line(text: str, page: int | None, line: int) -> str | None:
    pages = text.split(_PAGE_BREAK) if page is not None else [text]
    index = (page or 1) - 1
    if index < 0 or index >= len(pages):
        return None
    lines = pages[index].splitlines()
    return lines[line - 1] if 1 <= line <= len(lines) else None


def _csv_row(text: str, number: int) -> str | None:
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        for row in reader:
            if reader.line_num == number:
                out = io.StringIO()
                csv.writer(out).writerow(row)
                return out.getvalue().rstrip("\r\n")
    except csv.Error:
        return None
    return None


_JSON_STEP = re.compile(r"\.([^.\[\]]+)|\[(\d+)\]")


def _json_value(text: str, path: str) -> str | None:
    try:
        node: Any = json.loads(text)
    except ValueError:
        return None
    rest = path[1:]
    steps = list(_JSON_STEP.finditer(rest))
    if "".join(m.group(0) for m in steps) != rest:
        return None
    for m in steps:
        key, idx = m.groups()
        if key is not None:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        else:
            if not isinstance(node, list) or int(idx) >= len(node):
                return None
            node = node[int(idx)]
    return json.dumps(node, ensure_ascii=False, default=str)


_XML_STEP = re.compile(r"^([A-Za-z_][\w.\-]*)(?:\[(\d+)\])?$")


def _xml_text(text: str, path: str) -> str | None:
    try:
        node: Element = fromstring(
            text.encode(), forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except (ParseError, ValueError, DefusedXmlException):
        return None
    steps = path.strip("/").split("/")
    if steps[0] != node.tag:
        return None
    for step in steps[1:]:
        m = _XML_STEP.match(step)
        if m is None:
            return None
        children = [c for c in node if c.tag == m[1]]
        pos = int(m[2]) if m[2] else 1
        if not 1 <= pos <= len(children):
            return None
        node = children[pos - 1]
    if len(node) == 0:
        return "".join(node.itertext()).strip()
    return " ".join(f"{c.tag}={''.join(c.itertext()).strip()}" for c in node)


_LINE_LOC = re.compile(r"^(?:page:(\d+),)?line:(\d+)$")
_ROW_LOC = re.compile(r"^row:(\d+)(?:,col:.+)?$")


def _locate(text: str, location: str) -> str | None:
    if m := _LINE_LOC.match(location):
        return _text_line(text, int(m[1]) if m[1] else None, int(m[2]))
    if m := _ROW_LOC.match(location):
        return _csv_row(text, int(m[1]))
    if location.startswith("$"):
        return _json_value(text, location)
    if location.startswith("/"):
        return _xml_text(text, location)
    return None


def _get_source_excerpt(ctx: ToolContext, args: SourceExcerptArgs) -> dict:
    if ctx.source_text is None:
        raise ToolRejected("no_source")
    found = _locate(ctx.source_text, args.location)
    if found is None:
        raise ToolRejected("unknown_location")
    return {
        "location": args.location,
        "text": found[: ctx.excerpt_chars],
        "truncated": len(found) > ctx.excerpt_chars,
    }


_INGESTION, _VALIDATION, _APPROVAL = "ingestion", "validation", "approval"

REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "lookup_inventory",
            "Current stock for up to 200 item names; null means the item is unknown.",
            LookupInventoryArgs,
            _lookup_inventory,
            frozenset({_VALIDATION, _APPROVAL}),
        ),
        ToolSpec(
            "recompute_totals",
            "Recompute line totals, subtotal, tax and total of this invoice from its lines.",
            NoArgs,
            _recompute_totals,
            frozenset({_VALIDATION, _APPROVAL}),
        ),
        ToolSpec(
            "get_findings",
            "Validation findings recorded for this run, optionally of one severity.",
            GetFindingsArgs,
            _get_findings,
            frozenset({_APPROVAL}),
        ),
        ToolSpec(
            "lookup_prior_invoice",
            "Earlier versions, run outcomes and payment status of this invoice identity.",
            NoArgs,
            _lookup_prior_invoice,
            frozenset({_VALIDATION, _APPROVAL}),
        ),
        ToolSpec(
            "get_source_excerpt",
            "A bounded excerpt of the source at an evidence location such as line:9, "
            "page:1,line:4, row:3, $.line_items[0].name or /invoice/header/date.",
            SourceExcerptArgs,
            _get_source_excerpt,
            frozenset({_APPROVAL}),
        ),
        ToolSpec(
            "list_item_aliases",
            "Known inventory item names and the alias rules normalization applies.",
            NoArgs,
            _list_item_aliases,
            frozenset({_INGESTION}),
        ),
    )
}


def _reject(reason: str) -> dict:
    return {"error": "tool_rejected", "reason": reason}


class Dispatcher:
    """The `ToolBox` the model sees: authorizes, validates, runs, audits; never raises."""

    def __init__(
        self, ctx: ToolContext, *, excerpt_chars: int, audit_conn: sqlite3.Connection
    ) -> None:
        self._ctx = replace(ctx, excerpt_chars=excerpt_chars)
        self._audit_conn = audit_conn  # the writable connection; handlers never get it

    def specs(self, agent: str) -> list[ToolSpec]:
        return [s for s in REGISTRY.values() if agent in s.allowed_agents]

    def call(self, agent: str, name: str, arguments_json: str) -> str:
        start = time.perf_counter()
        args: dict | None = None
        try:
            result, args = self._run(agent, name, arguments_json)
        except Exception:  # defensive: call() never raises
            result = {"error": "tool_failed"}
        text = json.dumps(result, default=str)
        self._audit(agent, name, args, result, len(text), start)
        return text

    def reject(self, agent: str, name: str, reason: str) -> str:
        """Answer a call that is refused before dispatch (e.g. over the per-turn cap); audited."""
        start = time.perf_counter()
        result = _reject(reason)
        text = json.dumps(result)
        self._audit(agent, name, None, result, len(text), start)
        return text

    def _run(self, agent: str, name: str, arguments_json: str) -> tuple[dict, dict | None]:
        spec = REGISTRY.get(name) if isinstance(name, str) else None
        if spec is None:
            return _reject("unknown_tool"), None
        if agent not in spec.allowed_agents:
            return _reject("unauthorized"), None
        try:
            parsed = spec.args_model.model_validate(json.loads(arguments_json or "{}"))
        except (ValueError, TypeError, ValidationError, RecursionError):
            return _reject("invalid_arguments"), None  # RecursionError: absurdly nested JSON
        args = parsed.model_dump(mode="json")
        try:
            with self._ctx.conn.query_only():
                return spec.handler(self._ctx, parsed), args
        except ToolRejected as e:
            return _reject(e.reason), args
        except Exception:
            return {"error": "tool_failed"}, args

    def _audit(
        self, agent: str, name: str, args: dict | None, result: dict, size: int, start: float
    ) -> None:
        error = result.get("error")
        payload = {
            "agent": agent,
            # never echo untrusted names; a non-string (unhashable) name must not raise here
            "tool": name if isinstance(name, str) and name in REGISTRY else "unknown",
            "args": args,
            "ok": error is None,
            "error": result.get("reason", error),
            "result_size": size,
            "duration_ms": int((time.perf_counter() - start) * 1000),
        }
        try:
            ledger.append_audit_event(
                self._audit_conn,
                self._ctx.run_id,
                "tool",
                "tool_call",
                payload,
                invoice_id=self._ctx.invoice_id,
                version_id=self._ctx.version_id,
            )
        except Exception:
            _log.warning("tool audit event could not be recorded")
