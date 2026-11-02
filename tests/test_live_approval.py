"""Live recommend -> critique -> one revision loop, driven through the service with a fake."""

import json
import logging
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import grpc
import pytest

from invoice_processing import intake, ledger, seed, storage
from invoice_processing.agents.state import Deps, InvoiceState
from invoice_processing.codes import (
    CritiqueIssue,
    ExecutionMode,
    FindingCode,
    ModelErrorCode,
    Recommendation,
    RunStatus,
)
from invoice_processing.policy import POLICY_VERSION
from invoice_processing.reasoning.xai import XaiProvider
from invoice_processing.schemas import NormalizedInvoice
from invoice_processing.service import process_invoice
from invoice_processing.settings import LiveSettings
from invoice_processing.storage import connect
from invoice_processing.workflow import build_graph
from tests.fakes.xai_client import FakeXaiClient, Parsed, Raise, ToolCalls, factory

EVAL = date(2026, 1, 31)
LIVE = ExecutionMode.live
SENTINEL = "sk-SENTINEL-123"
SETTINGS = LiveSettings(api_key=SENTINEL, model="grok-test")
INVOICES = Path("data/invoices")
INV_1001 = INVOICES / "invoice_1001.txt"
INV_1002 = INVOICES / "invoice_1002.txt"
THRESHOLD = Path("tests/fixtures/threshold")
FAILED_MESSAGE = "Model request failed. Payment was not attempted."


@pytest.fixture
def db(tmp_path) -> Path:
    path = tmp_path / "live.db"
    c = connect(path)
    storage.init_schema(c)
    seed.seed_inventory(c)
    c.close()
    return path


def rec(decision="approve", cited=(), summary="looks fine", reasons=None):
    cited = [c.value if isinstance(c, FindingCode) else c for c in cited]
    return {
        "recommendation": decision,
        "reasons": list(reasons) if reasons is not None else list(cited),
        "cited_codes": cited,
        "summary": summary,
    }


def crit(agrees=True, revised=None, omissions=(), high_value=False, issues=()):
    return {
        "agrees": agrees,
        "omissions": list(omissions),
        "high_value": high_value,
        "revised_recommendation": revised,
        "summary": "critique agrees" if agrees else "critique disagrees",
        "issues": list(issues),
    }


def provider_with(*script, settings=SETTINGS):
    client = FakeXaiClient(list(script))
    return XaiProvider(settings, factory(client)), client


def live(path, db, *script, settings=SETTINGS):
    provider, client = provider_with(*script, settings=settings)
    return process_invoice(path, LIVE, db, EVAL, provider=provider), client


def rows(db, sql, *args):
    c = connect(db)
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def n_payments(db) -> int:
    return rows(db, "SELECT COUNT(*) AS n FROM payments")[0]["n"]


def decision_rows(db, run_id):
    return rows(db, "SELECT * FROM decisions WHERE run_id = ?", run_id)


def events(db, run_id):
    c = connect(db)
    try:
        return ledger.list_audit_events(c, run_id)
    finally:
        c.close()


def model_steps(db, run_id) -> list[str]:
    return [
        e["payload"]["step"]
        for e in events(db, run_id)
        if e["stage"] == "model" and e["event"] == "model_call"
    ]


def system_prompts(client) -> list[str]:
    return [chat.messages[0].text for chat in client.chats]


# --- uncited blocker -------------------------------------------------------------------


def test_uncited_blocker_on_inv_1002_triggers_revision_and_rejects(db):
    r, client = live(
        INV_1002,
        db,
        Parsed(rec("approve", summary="all good")),
        Parsed(crit(agrees=True)),
        Parsed(rec("reject", cited=[FindingCode.quantity_exceeds_stock], summary="overstock")),
    )
    assert r.status is RunStatus.rejected
    assert CritiqueIssue.uncited_blocker in r.decision.critique_issues
    assert r.decision.initial_recommendation is Recommendation.approve
    assert r.decision.revised_recommendation is Recommendation.reject
    assert n_payments(db) == 0
    assert model_steps(db, r.run_id) == ["recommend", "critique", "revise"]
    assert client.remaining == 0


def test_gate_rejects_even_if_revision_still_says_approve(db):
    r, _ = live(
        INV_1002,
        db,
        Parsed(rec("approve")),
        Parsed(crit(agrees=True)),
        Parsed(rec("approve", summary="still fine")),
    )
    assert r.status is RunStatus.rejected and n_payments(db) == 0
    assert r.decision.final_decision.value == "rejected"


# --- model disagreement and the human decision -------------------------------------------


def _second_run(db, first, provider, action):
    """A later run of the same invoice version once a human has decided.

    Until P4-04 adds `review.approve`, the service treats the same invoice as a duplicate,
    so the test attaches a new run to the persisted version and runs the graph from
    validation, as that review flow will.
    """
    c = connect(db)
    try:
        c.execute(
            "INSERT INTO human_reviews (invoice_id, version, action, reviewer, reason, "
            "policy_version, created_at) VALUES (?, 1, ?, 'rev', 'checked', ?, ?)",
            (first.invoice_id, action, POLICY_VERSION, ledger.utcnow()),
        )
        version_id = c.execute(
            "SELECT version_id FROM runs WHERE run_id = ?", (first.run_id,)
        ).fetchone()[0]
        row = c.execute(
            "SELECT version, payload_json FROM invoice_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        source, raw = intake.read_source(INV_1001)
        run_id = ledger.start_run(c, LIVE, source.source_id, EVAL)
        ledger.attach_run(c, run_id, first.invoice_id, version_id)
        ledger.update_run_status(c, run_id, RunStatus.extracted)
        state = InvoiceState(
            run_id=run_id,
            mode=LIVE,
            evaluation_date=EVAL,
            source=source,
            raw=raw,
            invoice=NormalizedInvoice.model_validate_json(row["payload_json"]),
            invoice_id=first.invoice_id,
            version_id=version_id,
            version=row["version"],
            findings=[],
            status=RunStatus.extracted,
        )
        deps = Deps(conn=c, provider=provider, events=logging.getLogger("test.events"))
        return build_graph(deps, start="validation").invoke(state)
    finally:
        c.close()


def _reject_1001(db):
    return live(INV_1001, db, Parsed(rec("reject", summary="vendor unknown")), Parsed(crit()))


def test_reject_on_clean_1001_waits_for_a_human_then_approve_pays(db):
    first, client = _reject_1001(db)
    assert first.status is RunStatus.awaiting_human_approval
    assert FindingCode.model_disagreement in {f.code for f in first.findings}
    assert first.decision.revised_recommendation is None
    assert first.decision.critique_issues == []
    assert model_steps(db, first.run_id) == ["recommend", "critique"]  # no revision
    assert client.remaining == 0 and n_payments(db) == 0

    provider, _ = provider_with(Parsed(rec("reject")), Parsed(crit()))
    out = _second_run(db, first, provider, "approve")
    assert out["status"] is RunStatus.paid_mock
    assert out["receipt"].amount == Decimal("5000.00")
    assert n_payments(db) == 1


def test_reject_on_clean_1001_then_decline_is_never_paid(db):
    first, _ = _reject_1001(db)
    provider, _ = provider_with(Parsed(rec("reject")), Parsed(crit()))
    out = _second_run(db, first, provider, "decline")
    assert out["status"] is RunStatus.awaiting_human_approval
    assert n_payments(db) == 0


# --- threshold fixtures ----------------------------------------------------------------


def test_10000_01_with_threshold_scrutiny_waits_with_no_critique_issues(db):
    r, _ = live(
        THRESHOLD / "valid_10000_01.json",
        db,
        Parsed(rec("approve", summary="Total 10,000.01 is above the 10,000.00 threshold")),
        Parsed(crit(agrees=True, high_value=True)),
    )
    assert r.status is RunStatus.awaiting_human_approval
    assert r.decision.critique_issues == []
    assert "R3_high_value" in r.decision.reasons
    assert n_payments(db) == 0


def test_10000_01_without_threshold_mention_gets_a_revision(db):
    r, _ = live(
        THRESHOLD / "valid_10000_01.json",
        db,
        Parsed(rec("approve", summary="clean invoice")),
        Parsed(crit(agrees=True)),
        Parsed(rec("approve", summary="clean; above the high-value threshold")),
    )
    assert r.decision.critique_issues == [CritiqueIssue.missed_high_value_scrutiny]
    assert r.status is RunStatus.awaiting_human_approval and n_payments(db) == 0


def test_10000_00_approve_pays_live(db):
    r, _ = live(THRESHOLD / "valid_10000_00.json", db, Parsed(rec("approve")), Parsed(crit()))
    assert r.status is RunStatus.paid_mock
    assert r.receipt.amount == Decimal("10000.00")
    assert r.decision.critique_issues == []
    assert n_payments(db) == 1


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("valid_10000_00.json", RunStatus.paid_mock),
        ("valid_10000_01.json", RunStatus.awaiting_human_approval),
    ],
)
def test_threshold_fixtures_offline(db, name, status):
    r = process_invoice(THRESHOLD / name, ExecutionMode.offline, db, EVAL)
    assert r.status is status
    assert r.decision.critique_issues == []
    assert r.model_calls_used == 0 and r.model_calls_budget is None


# --- call counts, persistence and prompts ----------------------------------------------


def test_one_critique_and_at_most_one_revision(db):
    r, client = live(
        INV_1002,
        db,
        Parsed(rec("approve")),
        Parsed(crit(agrees=False, revised="reject")),
        Parsed(rec("reject", cited=[FindingCode.quantity_exceeds_stock])),
    )
    steps = model_steps(db, r.run_id)
    assert steps.count("critique") == 1 and steps.count("revise") == 1
    prompts = system_prompts(client)
    assert len(prompts) == 3
    assert sum("critique" in p.lower().split("\n", 1)[0] for p in prompts) == 1
    assert client.remaining == 0


def test_decision_and_audit_events_are_persisted(db):
    r, _ = live(
        INV_1002,
        db,
        Parsed(rec("approve")),
        Parsed(crit(agrees=True)),
        Parsed(rec("reject", cited=[FindingCode.quantity_exceeds_stock])),
    )
    (row,) = decision_rows(db, r.run_id)
    payload = json.loads(row["payload_json"])
    # INV-1002 states 15,000.00 and the recommendation never mentions the threshold
    assert payload["critique_issues"] == ["uncited_blocker", "missed_high_value_scrutiny"]
    assert payload["revised_recommendation"] == "reject"
    assert payload["provider"] == "xai" and payload["model"] == "grok-test"
    assert payload["prompt_version"] == "recommend.v1,critique.v1,revise.v1"
    assert payload["model_calls_used"] == 3 == r.model_calls_used
    assert row["mode"] == "live"
    approval = [e for e in events(db, r.run_id) if e["stage"] == "approval"]
    assert [e["event"] for e in approval] == ["recommendation", "critique", "revision", "decision"]
    assert approval[1]["payload"]["issues"] == payload["critique_issues"]
    model = [e["payload"] for e in events(db, r.run_id) if e["stage"] == "model"]
    assert [m["step"] for m in model] == ["recommend", "critique", "revise"]
    assert all(m["input_tokens"] > 0 and m["attempt"] == 1 for m in model)
    assert r.model_calls_budget == 6 and not r.recoverable and r.next_actions == []


def test_invoice_data_is_delimited_and_no_key_or_hidden_reasoning_leaks(db):
    _, client = live(THRESHOLD / "valid_10000_00.json", db, Parsed(rec()), Parsed(crit()))
    for chat in client.chats:
        user = chat.messages[1].text
        assert user.startswith("<<<INVOICE_DATA\n") and user.endswith("\nINVOICE_DATA>>>")
        assert "TH-10000-00" in user
    blob = json.dumps(rows(db, "SELECT payload_json FROM audit_events"))
    blob += json.dumps(rows(db, "SELECT payload_json FROM decisions"))
    assert SENTINEL not in blob and "HIDDEN-REASONING" not in blob
    assert all(SENTINEL not in r.text for r in client.requests)


# --- tool loop and budget --------------------------------------------------------------


def _assert_failed_without_decision(db, r, code):
    assert r.status is RunStatus.failed
    assert r.errors == [code.value]
    assert r.error_message == FAILED_MESSAGE
    assert r.recoverable is True
    assert r.next_actions == ["retry", "run offline as a separate simulation"]
    assert r.decision is None and decision_rows(db, r.run_id) == []
    assert n_payments(db) == 0
    (run,) = rows(
        db, "SELECT status, error_code, error_message FROM runs WHERE run_id = ?", r.run_id
    )
    assert run == {"status": "failed", "error_code": code.value, "error_message": FAILED_MESSAGE}


def test_runaway_tool_loop_fails_without_decision_or_payment(db):
    calls = ToolCalls([("lookup_inventory", {"items": ["WidgetA"]})])
    r, client = live(INV_1001, db, *([calls] * 4))
    _assert_failed_without_decision(db, r, ModelErrorCode.model_tool_loop_exceeded)
    assert r.model_calls_used == 1
    assert [x.kind for x in client.requests] == ["sample"] * 4  # first sample + 3 tool turns
    assert FindingCode.currency_assumed_usd in {f.code for f in r.findings}  # findings kept
    model = [e["payload"] for e in events(db, r.run_id) if e["stage"] == "model"]
    assert [(m["step"], m["tool_turns"]) for m in model] == [("recommend", 3)]


def test_three_tool_turns_then_answer_consume_one_budget_unit(db):
    calls = ToolCalls([("lookup_inventory", {"items": ["WidgetA"]})])
    r, _ = live(INV_1001, db, calls, calls, calls, Parsed(rec()), Parsed(crit()))
    assert r.status is RunStatus.paid_mock
    assert r.model_calls_used == 2
    model = [e["payload"] for e in events(db, r.run_id) if e["stage"] == "model"]
    assert [(m["step"], m["tool_turns"]) for m in model] == [("recommend", 3), ("critique", 0)]
    tools = [e for e in events(db, r.run_id) if e["stage"] == "tool"]
    assert len(tools) == 3


def test_budget_two_fails_before_the_revision_request(db):
    settings = replace(SETTINGS, call_budget=2)
    r, client = live(
        INV_1002,
        db,
        Parsed(rec("approve")),
        Parsed(crit(agrees=False, revised="reject")),
        settings=settings,
    )
    _assert_failed_without_decision(db, r, ModelErrorCode.model_budget_exhausted)
    assert r.model_calls_used == 2 and r.model_calls_budget == 2
    assert len(client.chats) == 2  # recommend + critique; the revision was never sent
    assert model_steps(db, r.run_id) == ["recommend", "critique"]


def test_transport_timeout_once_counts_against_the_budget(db):
    r, client = live(
        INV_1001,
        db,
        Raise(grpc.StatusCode.DEADLINE_EXCEEDED),
        Parsed(rec()),
        Parsed(crit()),
    )
    assert r.status is RunStatus.paid_mock
    assert r.model_calls_used == 3
    assert r.decision.model_calls_used == 3
    model = [e["payload"] for e in events(db, r.run_id) if e["stage"] == "model"]
    assert [(m["step"], m["attempt"]) for m in model] == [
        ("recommend", 1),
        ("recommend", 2),
        ("critique", 1),
    ]


@pytest.mark.parametrize(
    "error",
    [grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.UNAVAILABLE],
)
def test_model_error_on_critique_leaves_no_decision(db, error):
    r, _ = live(INV_1001, db, Parsed(rec()), Raise(error), Raise(error))
    code = (
        ModelErrorCode.model_auth_error
        if error is grpc.StatusCode.UNAUTHENTICATED
        else ModelErrorCode.model_unavailable
    )
    _assert_failed_without_decision(db, r, code)
    approval = [e["event"] for e in events(db, r.run_id) if e["stage"] == "approval"]
    assert approval == ["recommendation", "model_failed"]


# --- offline -----------------------------------------------------------------------------


def test_offline_1001_uses_no_model_calls(db):
    r = process_invoice(INV_1001, ExecutionMode.offline, db, EVAL)
    assert r.status is RunStatus.paid_mock
    assert r.model_calls_used == 0 and r.model_calls_budget is None
    assert not r.recoverable and r.next_actions == []
    assert [e for e in events(db, r.run_id) if e["stage"] == "model"] == []


# --- deterministic critique checks -----------------------------------------------------


@pytest.mark.parametrize(
    ("decision", "cited", "summary", "total", "expected"),
    [
        ("approve", [], "fine", "5000.00", [CritiqueIssue.uncited_blocker]),
        ("review", [], "fine", "5000.00", [CritiqueIssue.uncited_blocker]),
        ("reject", [], "fine", "5000.00", []),  # a reject cannot wrongly clear a blocker
        ("approve", ["zero_stock"], "fine", "5000.00", []),
        ("reject", ["zero_stock"], "big", "10000.01", [CritiqueIssue.missed_high_value_scrutiny]),
        ("reject", ["zero_stock"], "over the THRESHOLD", "10000.01", []),
        ("reject", ["zero_stock"], "limit 10,000.00 exceeded", "10000.01", []),
        (
            "reject",
            ["zero_stock"],
            "total 10,000.01",
            "10000.01",
            [CritiqueIssue.missed_high_value_scrutiny],
        ),
        ("reject", ["zero_stock"], "fine", "10000.00", []),
    ],
)
def test_critique_checks(decision, cited, summary, total, expected):
    from invoice_processing.agents.approval import critique_checks
    from invoice_processing.schemas import ApprovalRecommendation
    from tests.helpers import finding, inv_1001

    inv = inv_1001()
    inv = inv.model_copy(update={"stated": inv.stated.model_copy(update={"total": Decimal(total)})})
    r = ApprovalRecommendation(
        **rec(decision, cited=cited, summary=summary), mode="live", provider="xai", model="m"
    )
    blocker = finding(FindingCode.zero_stock)
    assert critique_checks(inv, [blocker], r, Decimal("10000.00")) == expected
