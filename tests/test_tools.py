import json
import random
import sqlite3

import pytest

from invoice_processing import intake, ledger, seed
from invoice_processing.agents import ingestion
from invoice_processing.agents.state import Deps, make_session
from invoice_processing.reasoning.schema_check import unsupported_keywords
from invoice_processing.reasoning.xai import XaiProvider
from invoice_processing.settings import LiveSettings
from invoice_processing.tools import REGISTRY, Dispatcher, ReadOnlyConnection, ToolContext
from tests.test_agents import INV_1001, _received

SECRET_LINE = "  WidgetA    qty: 10    unit price: $250.00"


@pytest.fixture
def run_ctx(conn):
    seed.seed_inventory(conn)
    source, raw = intake.read_source(INV_1001)
    state = _received(conn, source, raw)
    import logging

    from invoice_processing.reasoning.offline import OfflineSimulator

    deps = Deps(conn=conn, provider=OfflineSimulator(), events=logging.getLogger("t"))
    state = {**state, **ingestion.run(state, deps)}
    return state, deps


def _dispatcher(conn, state, *, chars=4000, **over):
    ctx = ToolContext(
        conn=ReadOnlyConnection(conn),
        run_id=state["run_id"],
        invoice=state.get("invoice"),
        invoice_id=state.get("invoice_id"),
        version_id=state.get("version_id"),
        source_text=state.get("source_text"),
        **over,
    )
    return Dispatcher(ctx, excerpt_chars=chars, audit_conn=conn)


def _call(d, agent, name, args):
    return json.loads(d.call(agent, name, args if isinstance(args, str) else json.dumps(args)))


def test_rejections(run_ctx):
    state, deps = run_ctx
    d = _dispatcher(deps.conn, state)
    rejected = lambda reason: {"error": "tool_rejected", "reason": reason}  # noqa: E731
    assert _call(d, "approval", "list_item_aliases", {}) == rejected("unauthorized")
    assert _call(d, "approval", "lookup_inventory", {"items": "WidgetA"}) == rejected(
        "invalid_arguments"
    )
    too_many = {"items": [f"i{n}" for n in range(201)]}
    assert _call(d, "approval", "lookup_inventory", too_many) == rejected("invalid_arguments")
    assert _call(d, "approval", "lookup_inventory", {"items": ["a"], "x": 1}) == rejected(
        "invalid_arguments"
    )
    assert _call(d, "approval", "pay_invoice", {}) == rejected("unknown_tool")
    assert _call(d, "approval", "lookup_inventory", "{not json") == rejected("invalid_arguments")
    assert _call(d, "approval", "lookup_inventory", "[1]") == rejected("invalid_arguments")


def test_lookup_inventory_and_no_writes(run_ctx):
    state, deps = run_ctx
    d = _dispatcher(deps.conn, state)
    out = _call(d, "approval", "lookup_inventory", {"items": ["WidgetA", "FakeItem", "Nope"]})
    assert out["stock"] == {"WidgetA": 15, "FakeItem": 0, "Nope": None}
    before = deps.conn.execute("SELECT item, stock FROM inventory ORDER BY item").fetchall()
    names = ["WidgetA", "WidgetB", "GadgetX", "FakeItem", "'; DROP TABLE inventory;--", "x"]
    rng = random.Random(1)
    for _ in range(50):
        _call(d, "approval", "lookup_inventory", {"items": rng.sample(names, rng.randint(1, 6))})
    after = deps.conn.execute("SELECT item, stock FROM inventory ORDER BY item").fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_read_only_connection_refuses_writes(conn):
    ro = ReadOnlyConnection(conn)
    assert ro.execute("  select 1").fetchone()[0] == 1
    for sql in ("DELETE FROM inventory", "UPDATE inventory SET stock=0", "DROP TABLE inventory"):
        with pytest.raises(PermissionError):
            ro.execute(sql)
    assert not hasattr(ro, "executemany") and not hasattr(ro, "commit")


def test_registry_whitelist():
    assert set(REGISTRY) == {
        "lookup_inventory",
        "recompute_totals",
        "get_findings",
        "lookup_prior_invoice",
        "get_source_excerpt",
        "list_item_aliases",
    }
    for name in REGISTRY:
        assert not any(w in name for w in ("pay", "write", "update", "delete", "approve", "policy"))
    assert REGISTRY["list_item_aliases"].allowed_agents == {"ingestion"}
    assert REGISTRY["get_findings"].allowed_agents == {"approval"}


def test_schemas_are_provider_safe():
    for spec in REGISTRY.values():
        schema = spec.json_schema()
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert unsupported_keywords(schema) == []


def test_specs_filtered_by_agent(run_ctx):
    state, deps = run_ctx
    d = _dispatcher(deps.conn, state)
    assert {s.name for s in d.specs("ingestion")} == {"get_source_excerpt", "list_item_aliases"}
    assert "list_item_aliases" not in {s.name for s in d.specs("approval")}
    assert d.specs("stranger") == []


def test_audit_event_per_call_without_excerpt(run_ctx):
    state, deps = run_ctx
    d = _dispatcher(deps.conn, state)
    _call(d, "approval", "get_source_excerpt", {"location": "line:9"})
    _call(d, "approval", "list_item_aliases", {})
    _call(d, "approval", "SECRET_TOOL_NAME", {})
    events = [
        e for e in ledger.list_audit_events(deps.conn, state["run_id"]) if e["stage"] == "tool"
    ]
    assert [e["event"] for e in events] == ["tool_call"] * 3
    ok, unauthorized, unknown = (e["payload"] for e in events)
    assert ok["ok"] is True and ok["args"] == {"location": "line:9"} and ok["result_size"] > 0
    assert unauthorized["ok"] is False and unauthorized["error"] == "unauthorized"
    assert unknown["tool"] == "unknown" and "SECRET_TOOL_NAME" not in json.dumps(unknown)
    assert "duration_ms" in ok and ok["agent"] == "approval"
    assert "WidgetA" not in json.dumps([e["payload"] for e in events])


def test_source_excerpt_line_and_cap(run_ctx):
    state, deps = run_ctx
    d = _dispatcher(deps.conn, state)
    out = _call(d, "approval", "get_source_excerpt", {"location": "line:9"})
    assert out["text"] == SECRET_LINE and out["truncated"] is False
    capped = _call(
        _dispatcher(deps.conn, state, chars=10),
        "approval",
        "get_source_excerpt",
        {"location": "line:9"},
    )
    assert capped["text"] == SECRET_LINE[:10] and capped["truncated"] is True
    for bad in ("line:999", "nonsense", "page:2,line:1", "$.a", "/invoice", "row:99"):
        assert _call(d, "approval", "get_source_excerpt", {"location": bad}) == {
            "error": "tool_rejected",
            "reason": "unknown_location",
        }


def test_source_excerpt_formats():
    def ctx(text):
        return ToolContext(conn=None, run_id="r", source_text=text)  # type: ignore[arg-type]

    spec = REGISTRY["get_source_excerpt"]
    from invoice_processing.tools import SourceExcerptArgs

    def get(text, loc):
        return spec.handler(ctx(text), SourceExcerptArgs(location=loc))["text"]

    assert get("a\nb\n\fc".replace("\n\fc", "\n\f\nc\nd"), "page:2,line:2") == "d"
    assert get('{"line_items": [{"name": "W"}]}', "$.line_items[0].name") == '"W"'
    assert get("h,h2\n1,2\n", "row:2,col:h2") == "1,2"
    xml = (
        "<invoice><header><date>2026-01-01</date></header><line_items>"
        "<item><name>A</name></item><item><name>B</name></item></line_items></invoice>"
    )
    assert get(xml, "/invoice/header/date") == "2026-01-01"
    assert get(xml, "/invoice/line_items/item[2]/name") == "B"


def test_recompute_findings_prior(run_ctx):
    state, deps = run_ctx
    d = _dispatcher(deps.conn, state)
    totals = _call(d, "approval", "recompute_totals", {})
    assert totals["computed"]["total"] == "5000.00"
    assert _call(d, "approval", "get_findings", {"severity": "blocker"}) == {"findings": []}
    assert _call(d, "approval", "get_findings", {"severity": "bogus"})["error"] == "tool_rejected"
    prior = _call(d, "approval", "lookup_prior_invoice", {})
    assert prior["known"] is True and prior["payment"] is None and prior["runs"] == []
    blank = _dispatcher(deps.conn, {"run_id": state["run_id"]})
    assert _call(blank, "approval", "recompute_totals", {})["reason"] == "no_invoice"
    assert _call(blank, "approval", "lookup_prior_invoice", {}) == {"known": False}
    assert _call(blank, "approval", "get_source_excerpt", {"location": "line:1"})["reason"] == (
        "no_source"
    )


def test_aliases(run_ctx):
    state, deps = run_ctx
    out = _call(_dispatcher(deps.conn, state), "ingestion", "list_item_aliases", {})
    assert "WidgetA" in out["known_items"] and "Vndr" in out["label_spellings"]["vendor"]


def test_handler_failure_is_tool_failed(run_ctx, monkeypatch):
    state, deps = run_ctx
    d = _dispatcher(deps.conn, state)

    def boom(*a):
        raise sqlite3.OperationalError("secret detail")

    spec = REGISTRY["lookup_inventory"]
    monkeypatch.setitem(
        REGISTRY, "lookup_inventory", type(spec)(**{**spec.__dict__, "handler": boom})
    )
    out = d.call("approval", "lookup_inventory", '{"items": ["a"]}')
    assert json.loads(out) == {"error": "tool_failed"} and "secret" not in out


def test_make_session_wires_dispatcher_only_for_live(run_ctx):
    state, deps = run_ctx
    assert make_session(deps, state).tools.specs("approval") == []
    live = XaiProvider(LiveSettings(api_key="sk-SENTINEL-123", model="m"), lambda s: None)
    session = make_session(Deps(deps.conn, live, deps.events), state)
    assert isinstance(session.tools, Dispatcher) and session.budget == 6
    out = json.loads(session.tools.call("approval", "lookup_inventory", '{"items":["WidgetA"]}'))
    assert out["stock"] == {"WidgetA": 15}
    assert state["source_text"].startswith("INVOICE")
