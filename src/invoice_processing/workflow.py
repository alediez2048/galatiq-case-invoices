"""LangGraph workflow: ingestion -> validation -> approval -> (payment | outcome)."""

from functools import partial
from typing import Literal

from langgraph.graph import END, START, StateGraph

from invoice_processing.agents import approval as approval_agent
from invoice_processing.agents import ingestion, payment, validation
from invoice_processing.agents.state import Deps, InvoiceState
from invoice_processing.codes import RunStatus
from invoice_processing.transitions import RUN_TRANSITIONS

__all__ = ["RUN_TRANSITIONS", "build_graph", "route_after", "route_after_approval"]

_NEXT_AFTER_STATUS = {
    RunStatus.extracted: "validation",
    RunStatus.validated: "approval",
}


def route_after(state: InvoiceState) -> str:
    """Next node name, or "end" when the run failed or has nothing further to do."""
    status = state.get("status")
    if status is RunStatus.failed:
        return "end"
    return _NEXT_AFTER_STATUS.get(status, "end")


def route_after_approval(state: InvoiceState) -> Literal["payment", "outcome", "end"]:
    status = state.get("status")
    if status is RunStatus.approved:
        return "payment"
    if status is RunStatus.failed:
        return "end"
    return "outcome"


def build_graph(
    deps: Deps,
    start: Literal["ingestion", "validation"] = "ingestion",
    approval: Literal["agent", "human"] = "agent",
):
    """`approval="human"` runs `approval.resume` (a human-review run: no model call) in the
    approval node; the edges after it are the same."""
    # Node functions are resolved from their modules here so tests can patch them.
    graph = StateGraph(InvoiceState)
    if start == "ingestion":
        graph.add_node("ingestion", partial(ingestion.run, deps=deps))
    graph.add_node("validation", partial(validation.run, deps=deps))
    node = approval_agent.resume if approval == "human" else approval_agent.run
    graph.add_node("approval", partial(node, deps=deps))
    graph.add_node("payment", partial(payment.pay_node, deps=deps))
    graph.add_node("outcome", partial(payment.outcome_node, deps=deps))

    graph.add_edge(START, start)
    if start == "ingestion":
        graph.add_conditional_edges(
            "ingestion", route_after, {"validation": "validation", "end": END}
        )
    graph.add_conditional_edges("validation", route_after, {"approval": "approval", "end": END})
    graph.add_conditional_edges(
        "approval",
        route_after_approval,
        {"payment": "payment", "outcome": "outcome", "end": END},
    )
    graph.add_edge("payment", END)
    graph.add_edge("outcome", END)
    return graph.compile()
