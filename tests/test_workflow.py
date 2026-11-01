import logging
from datetime import date

import pytest

from invoice_processing import ledger, seed, transitions, workflow
from invoice_processing.agents.state import Deps, InvoiceState
from invoice_processing.codes import ExecutionMode, RunStatus
from invoice_processing.reasoning.offline import OfflineSimulator
from invoice_processing.workflow import build_graph, route_after, route_after_approval

EVAL = date(2026, 1, 20)


def fake_deps(conn=None) -> Deps:
    import sqlite3

    c = conn or sqlite3.connect(":memory:")
    return Deps(conn=c, provider=OfflineSimulator(), events=logging.getLogger("test.events"))


def test_run_transitions_reexported():
    assert workflow.RUN_TRANSITIONS is transitions.RUN_TRANSITIONS


@pytest.mark.parametrize("status", list(RunStatus))
def test_route_after_table(status):
    expected_end = status not in (RunStatus.extracted, RunStatus.validated)
    result = route_after({"status": status})
    if status is RunStatus.failed:
        assert result == "end"
    if status is RunStatus.extracted:
        assert result == "validation"
    if status is RunStatus.validated:
        assert result == "approval"
    if expected_end:
        assert result == "end"


@pytest.mark.parametrize("status", list(RunStatus))
def test_payment_unreachable_unless_approved(status):
    route = route_after_approval({"status": status})
    assert (route == "payment") == (status is RunStatus.approved)
    if status is RunStatus.failed:
        assert route == "end"
    elif status is not RunStatus.approved:
        assert route == "outcome"


def test_payment_only_reachable_from_approval():
    g = build_graph(fake_deps()).get_graph()
    assert {e.source for e in g.edges if e.target == "payment"} == {"approval"}


def test_graph_nodes_and_start():
    names = set(build_graph(fake_deps()).get_graph().nodes)
    assert {"ingestion", "validation", "approval", "payment", "outcome"} <= names
    g2 = build_graph(fake_deps(), start="validation").get_graph()
    assert "ingestion" not in g2.nodes
    assert {e.target for e in g2.edges if e.source == "__start__"} == {"validation"}


def test_start_at_validation_reaches_paid_mock(conn):
    from pathlib import Path

    from invoice_processing import intake
    from invoice_processing.agents import ingestion

    seed.seed_inventory(conn)
    deps = fake_deps(conn)
    source, raw = intake.read_source(Path("data/invoices/invoice_1001.txt"))
    ledger.record_source(conn, source)
    run_id = ledger.start_run(conn, ExecutionMode.offline, source.source_id, EVAL)
    state = InvoiceState(
        run_id=run_id,
        mode=ExecutionMode.offline,
        evaluation_date=EVAL,
        source=source,
        raw=raw,
    )
    state = {**state, **ingestion.run(state, deps)}
    out = build_graph(deps, start="validation").invoke(state)
    assert out["status"] is RunStatus.paid_mock
    assert out["receipt"].amount is not None
    assert ledger.get_run_status(conn, run_id) is RunStatus.paid_mock


def test_patching_agent_run_takes_effect(conn, monkeypatch):
    from invoice_processing.agents import ingestion

    calls = []

    def fake(state, deps):
        calls.append(1)
        return {"status": RunStatus.failed, "error_code": "x"}

    monkeypatch.setattr(ingestion, "run", fake)
    out = build_graph(fake_deps(conn)).invoke({"status": RunStatus.received})
    assert calls == [1] and out["status"] is RunStatus.failed
