"""Payment agent nodes. This module is the only place the graph reaches payments.pay."""

from invoice_processing import ledger, payments
from invoice_processing.agents.state import Deps, InvoiceState, emit
from invoice_processing.codes import RunStatus, Severity
from invoice_processing.observability import stage_timer

PAY_STAGE = "payment"
OUTCOME_STAGE = "outcome"


def pay_node(state: InvoiceState, deps: Deps) -> dict:
    timings = state.get("timings_ms", {})
    with stage_timer() as t:
        try:
            result = payments.pay(
                deps.conn, state["invoice_id"], state["version_id"], state["run_id"]
            )
        except payments.PaymentNotAuthorized as e:
            update: dict = {
                "status": RunStatus.failed,
                "error_code": f"payment_not_authorized:{e.reason}",
            }
            emit(deps, {**state, **update}, PAY_STAGE, "payment_refused", reason=e.reason)
        else:
            ledger.update_run_status(deps.conn, state["run_id"], RunStatus.paid_mock)
            receipt = result.receipt
            update = {"receipt": receipt, "status": RunStatus.paid_mock}
            emit(
                deps,
                {**state, **update},
                PAY_STAGE,
                "paid",
                receipt_id=receipt.receipt_id,
                amount=str(receipt.amount),
                currency=receipt.currency,
                created=result.created,
            )
    return {**update, "timings_ms": {**timings, PAY_STAGE: t["duration_ms"]}}


def outcome_node(state: InvoiceState, deps: Deps) -> dict:
    timings = state.get("timings_ms", {})
    with stage_timer() as t:
        status = state.get("status")
        if status == RunStatus.rejected:
            blockers = [f.code for f in state.get("findings", []) if f.severity == Severity.blocker]
            payments.record_rejection(
                deps.conn,
                state["run_id"],
                state.get("invoice_id"),
                state.get("version_id"),
                blockers,
            )
        else:
            emit(deps, state, OUTCOME_STAGE, "waiting")
    return {"timings_ms": {**timings, OUTCOME_STAGE: t["duration_ms"]}}
