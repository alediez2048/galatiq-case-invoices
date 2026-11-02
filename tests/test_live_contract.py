"""Live-path contract (P3-09): every model failure code, tool authorization and offline parity,
all through `process_invoice(mode=live)` with the scripted fake client."""

import ast
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import grpc
import pytest

from invoice_processing import ledger, seed, storage
from invoice_processing.codes import ExecutionMode, FindingCode, ModelErrorCode, RunStatus
from invoice_processing.reasoning.base import PolicyContext
from invoice_processing.reasoning.errors import ModelError
from invoice_processing.reasoning.session import ModelSession
from invoice_processing.reasoning.xai import XaiProvider
from invoice_processing.schemas import CritiqueOutput, ExtractionProposals, RecommendationOutput
from invoice_processing.service import process_invoice
from invoice_processing.settings import LiveSettings
from invoice_processing.storage import connect
from tests.fakes.xai_client import (
    FakeChat,
    FakeXaiClient,
    Malformed,
    Parsed,
    Raise,
    ToolCalls,
    factory,
)
from tests.helpers import inv_1001
from tests.test_acceptance import CASES

EVAL = date(2026, 1, 31)
LIVE = ExecutionMode.live
SETTINGS = LiveSettings(api_key="sk-SENTINEL-123", model="grok-test")
INVOICES = Path("data/invoices")
INV_1001 = INVOICES / "invoice_1001.txt"
INV_1002 = INVOICES / "invoice_1002.txt"
UNAVAILABLE = Raise(grpc.StatusCode.UNAVAILABLE)
TIMEOUT = Raise(grpc.StatusCode.DEADLINE_EXCEEDED)

#: error code -> ids of the tests in this module that produce it


@pytest.fixture
def db(tmp_path) -> Path:
    path = tmp_path / "contract.db"
    c = connect(path)
    storage.init_schema(c)
    seed.seed_inventory(c)
    c.close()
    return path


def rec(decision="approve", cited=()):
    cited = [c.value if isinstance(c, FindingCode) else c for c in cited]
    return {"recommendation": decision, "reasons": cited, "cited_codes": cited, "summary": "ok"}


def crit():
    return {
        "agrees": True,
        "omissions": [],
        "high_value": False,
        "revised_recommendation": None,
        "summary": "critique agrees",
        "issues": [],
    }


def live(path, db, *script, settings=SETTINGS):
    client = FakeXaiClient(list(script))
    provider = XaiProvider(settings, factory(client))
    return process_invoice(path, LIVE, db, EVAL, provider=provider), client


def events(db, run_id):
    c = connect(db)
    try:
        return ledger.list_audit_events(c, run_id)
    finally:
        c.close()


def n_payments(db) -> int:
    c = connect(db)
    try:
        return c.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    finally:
        c.close()


def assert_failed(r, db, code: ModelErrorCode):
    assert r.status is RunStatus.failed
    assert r.errors == [code.value]
    assert r.recoverable is True and r.next_actions
    assert r.receipt is None and n_payments(db) == 0


# --- happy path and recoveries ------------------------------------------------------------


def test_happy_path_with_one_inventory_lookup_pays(db):
    lookup = ToolCalls([("lookup_inventory", {"items": ["WidgetA", "WidgetB"]})])
    r, client = live(INV_1001, db, lookup, Parsed(rec()), Parsed(crit()))
    assert r.status is RunStatus.paid_mock and r.receipt is not None
    assert client.remaining == 0
    tools = [e["payload"] for e in events(db, r.run_id) if e["stage"] == "tool"]
    assert [(t["tool"], t["ok"]) for t in tools] == [("lookup_inventory", True)]
    assert n_payments(db) == 1


NO_VENDOR_TXT = (
    "INVOICE\n\nInvoice Number: INV-7001\nDate: 2026-01-15\nDue Date: 2026-02-01\n\n"
    "Items:\n  WidgetA    qty: 2    unit price: $250.00\n\nSubtotal: $500.00\n"
    "Tax (0%): $0.00\nTotal Amount: $500.00\n\nThank you.\nAcme Parts Ltd\n"
)
VENDOR_PROPOSAL = {
    "field": "vendor",
    "value": "Acme Parts Ltd",
    "quote": "Acme Parts Ltd",
    "location": "line:15",
}


@pytest.fixture
def no_vendor(tmp_path) -> Path:
    path = tmp_path / "no_vendor.txt"
    path.write_text(NO_VENDOR_TXT)
    return path


def test_malformed_extraction_assist_is_repaired_once(db, no_vendor):
    r, client = live(
        no_vendor,
        db,
        Malformed('{"proposals": "not a list"}'),
        Parsed({"proposals": [VENDOR_PROPOSAL]}),
        Parsed(rec()),
        Parsed(crit()),
    )
    assert r.status is RunStatus.paid_mock
    assert client.remaining == 0
    assert [q.kind for q in client.requests].count("parse") == 4  # assist x2, recommend, critique


def test_timeout_then_success_retries_the_transport(db):
    r, _ = live(INV_1001, db, TIMEOUT, Parsed(rec()), Parsed(crit()))
    assert r.status is RunStatus.paid_mock
    assert r.model_calls_used == 3  # the retry is charged


def test_rate_limit_then_success(db):
    limited = Raise(grpc.StatusCode.RESOURCE_EXHAUSTED)
    r, _ = live(INV_1001, db, limited, Parsed(rec()), Parsed(crit()))
    assert r.status is RunStatus.paid_mock


# --- every ModelErrorCode ---------------------------------------------------------------------


def test_timeout_twice_fails_recoverably(db):
    r, _ = live(INV_1001, db, TIMEOUT, TIMEOUT)
    assert_failed(r, db, ModelErrorCode.model_timeout)


def test_auth_error(db):
    r, client = live(INV_1001, db, Raise(grpc.StatusCode.UNAUTHENTICATED))
    assert_failed(r, db, ModelErrorCode.model_auth_error)
    assert len(client.requests) == 1  # never retried


def test_rate_limited_twice(db):
    limited = Raise(grpc.StatusCode.RESOURCE_EXHAUSTED)
    r, _ = live(INV_1001, db, limited, limited)
    assert_failed(r, db, ModelErrorCode.model_rate_limited)


def test_unavailable_twice(db):
    r, _ = live(INV_1001, db, UNAVAILABLE, UNAVAILABLE)
    assert_failed(r, db, ModelErrorCode.model_unavailable)


def test_invalid_output(db):
    r, _ = live(INV_1001, db, Malformed('{"recommendation": "maybe"}'))
    assert_failed(r, db, ModelErrorCode.model_output_invalid)


def test_empty_answer_without_tools_is_a_refusal_and_with_tools_a_tool_loop(db):
    # Through the service every step offers tools, where an empty final answer is read as a
    # runaway tool loop; `model_refused` is therefore only reachable on a tool-less session.
    r, _ = live(INV_1001, db, Malformed(""))
    assert r.errors == [ModelErrorCode.model_tool_loop_exceeded.value]

    provider = XaiProvider(SETTINGS, factory(FakeXaiClient([Malformed("")])))
    session = ModelSession(budget=6)
    with pytest.raises(ModelError) as info:
        provider.recommend(inv_1001(), [], PolicyContext("p", Decimal("10000")), session)
    assert info.value.code is ModelErrorCode.model_refused


def test_budget_exhaustion(db):
    from dataclasses import replace

    r, client = live(
        INV_1002,
        db,
        Parsed(rec("approve")),
        Parsed({**crit(), "agrees": False, "revised_recommendation": "reject"}),
        settings=replace(SETTINGS, call_budget=2),
    )
    assert_failed(r, db, ModelErrorCode.model_budget_exhausted)
    assert r.model_calls_used == r.model_calls_budget == 2
    assert len(client.chats) == 2  # the revision was never sent


def test_runaway_tool_loop(db):
    lookup = ToolCalls([("lookup_inventory", {"items": ["WidgetA"]})])
    r, client = live(INV_1001, db, *[lookup] * 10)
    assert_failed(r, db, ModelErrorCode.model_tool_loop_exceeded)
    tools = [e for e in events(db, r.run_id) if e["stage"] == "tool"]
    assert len(tools) == 3  # the per-step turn cap
    assert client.remaining > 0


def _codes_asserted_by_tests() -> set[str]:
    """ModelErrorCode members a test in this module asserts: the code passed to
    `assert_failed(...)` or compared with `... is ModelErrorCode.<code>`. Read from the
    source, so the check does not depend on which tests ran or in what order."""
    tree = ast.parse(Path(__file__).read_text())
    found: set[str] = set()

    def member(node: ast.AST) -> str | None:
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "ModelErrorCode"
        ):
            return node.attr
        return None

    for fn in tree.body:
        if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith("test_")):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "assert_failed":
                found |= {m for a in node.args if (m := member(a))}
            elif isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.Is):
                found |= {m for c in node.comparators if (m := member(c))}
    return found


def test_every_model_error_code_is_produced_by_a_test():
    # static: fails if a ModelErrorCode is added without a test that produces it
    assert _codes_asserted_by_tests() == {c.name for c in ModelErrorCode}


# --- tool authorization -----------------------------------------------------------------------


def test_unauthorized_tool_request_is_audited_and_the_run_continues(db):
    pay = ToolCalls([("pay_invoice", {"invoice_number": "INV-1001", "amount": "1.00"})])
    r, client = live(INV_1001, db, pay, Parsed(rec()), Parsed(crit()))
    assert r.status is RunStatus.paid_mock and client.remaining == 0
    tools = [e["payload"] for e in events(db, r.run_id) if e["stage"] == "tool"]
    assert [(t["tool"], t["ok"], t["error"]) for t in tools] == [("unknown", False, "unknown_tool")]
    assert n_payments(db) == 1  # only the deterministic payment service paid, once


# --- parity with the offline corpus --------------------------------------------------------


class _ReasonableChat(FakeChat):
    """Answers each structured request the way the offline simulator would."""

    def sample(self):
        self._record("sample")
        return self._client._response(content="no tools needed")

    def parse(self, shape):
        self.response_format = shape
        self._record("parse")
        client: ReasonableClient = self._client
        if shape is ExtractionProposals:
            obj = {"proposals": []}
        elif shape is RecommendationOutput:
            obj = client.recommendation
        elif shape is CritiqueOutput:
            obj = {
                "agrees": True,
                "omissions": [],
                "high_value": False,
                "revised_recommendation": None,
                "summary": "agrees",
                "issues": [],
            }
        else:  # pragma: no cover
            raise AssertionError(f"unexpected shape {shape}")
        content = json.dumps(obj)
        return client._response(content=content), shape.model_validate_json(content)


class ReasonableClient(FakeXaiClient):
    def __init__(self, recommendation: dict) -> None:
        super().__init__([])
        self.recommendation = recommendation

        outer = self

        class _Chats:
            def create(self, model, *, messages=None, tools=None, **_):
                chat = _ReasonableChat(outer, model, list(messages or []), list(tools or []))
                outer.chats.append(chat)
                return chat

        self.chat = _Chats()


@pytest.mark.parametrize("name", sorted(CASES))
def test_reasonable_live_model_matches_the_offline_outcome(name, tmp_path):
    status, amount, _, _ = CASES[name]

    def fresh(label):
        path = tmp_path / f"{label}.db"
        c = connect(path)
        storage.init_schema(c)
        seed.seed_inventory(c)
        c.close()
        return path

    offline = process_invoice(INVOICES / name, ExecutionMode.offline, fresh("offline"), EVAL)
    assert offline.status is RunStatus(status)
    recommendation = {
        "recommendation": offline.decision.initial_recommendation.value,
        "reasons": offline.decision.reasons,
        "cited_codes": [r for r in offline.decision.reasons if r in FindingCode],
        "summary": "scripted reasonable model",
    }
    client = ReasonableClient(recommendation)
    provider = XaiProvider(SETTINGS, factory(client))
    live_db = fresh("live")
    r = process_invoice(INVOICES / name, LIVE, live_db, EVAL, provider=provider)

    assert r.status is RunStatus(status)
    assert r.mode is LIVE
    assert (r.receipt is not None) == (status == "paid_mock")
    if amount is not None:
        assert str(r.receipt.amount) == amount
    assert n_payments(live_db) == (1 if amount is not None else 0)
    assert r.model_calls_used <= SETTINGS.call_budget
