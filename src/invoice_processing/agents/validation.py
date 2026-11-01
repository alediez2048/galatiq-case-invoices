"""Validation agent: deterministic field, arithmetic, date, and inventory checks."""

from invoice_processing import ledger, validation
from invoice_processing.agents.state import Deps, InvoiceState, emit
from invoice_processing.codes import RunStatus
from invoice_processing.observability import stage_timer

STAGE = "validation"


def run(state: InvoiceState, deps: Deps) -> dict:
    timings = state.get("timings_ms", {})
    with stage_timer() as t:
        invoice = state["invoice"]
        computed, arithmetic = validation.reconcile_totals(invoice)
        findings = [
            *state.get("findings", []),
            *validation.check_required_fields(invoice),
            *validation.check_value_signs(invoice),
            *validation.check_due_date(invoice, state["evaluation_date"]),
            *arithmetic,
            *validation.check_inventory_against_db(
                deps.conn, validation.aggregate_quantities(invoice.lines)
            ),
        ]
        ledger.record_findings(deps.conn, state["run_id"], state.get("version_id"), findings)
        ledger.update_run_status(deps.conn, state["run_id"], RunStatus.validated)
        update = {
            "invoice": invoice.model_copy(update={"computed": computed}),
            "findings": findings,
            "status": RunStatus.validated,
        }
        emit(
            deps,
            {**state, **update},
            STAGE,
            "validated",
            codes=[f.code for f in findings],
        )
    return {**update, "timings_ms": {**timings, STAGE: t["duration_ms"]}}
