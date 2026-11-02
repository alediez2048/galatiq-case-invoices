"""Approval agent: recommend, critique once, then let the deterministic gate decide."""

from invoice_processing import ledger, policy
from invoice_processing.agents.state import Deps, InvoiceState, emit
from invoice_processing.codes import RunStatus
from invoice_processing.observability import stage_timer
from invoice_processing.reasoning.session import ModelSession
from invoice_processing.schemas import ApprovalDecision

STAGE = "approval"


def run(state: InvoiceState, deps: Deps) -> dict:
    timings = state.get("timings_ms", {})
    with stage_timer() as t:
        conn, run_id, provider = deps.conn, state["run_id"], deps.provider
        invoice = state["invoice"]
        findings = list(state.get("findings", []))
        ledger.update_run_status(conn, run_id, RunStatus.approval_pending)
        ctx = policy.context()
        session = ModelSession.for_provider(provider)

        initial = provider.recommend(invoice, findings, ctx, session)
        emit(
            deps,
            state,
            STAGE,
            "recommendation",
            recommendation=initial.recommendation.value,
            codes=initial.cited_codes,
        )
        critique = provider.critique(invoice, findings, initial, ctx, session)
        emit(
            deps,
            state,
            STAGE,
            "critique",
            agrees=critique.agrees,
            revised_recommendation=(
                critique.revised_recommendation.value if critique.revised_recommendation else None
            ),
        )
        final = critique.revised_recommendation or initial.recommendation

        review = ledger.get_human_review(
            conn, state["invoice_id"], state["version"], policy.POLICY_VERSION
        )
        gate = policy.evaluate(invoice, findings, final, review, version=state["version"])
        findings = [*findings, *gate.findings]
        ledger.record_findings(conn, run_id, state.get("version_id"), gate.findings)

        decision = ApprovalDecision(
            initial_recommendation=initial.recommendation,
            critique_summary=critique.summary,
            revised_recommendation=critique.revised_recommendation,
            final_decision=gate.outcome,
            reasons=gate.rule_ids,
            policy_version=policy.POLICY_VERSION,
            mode=provider.mode,
            provider=provider.provider,
            model=provider.model,
            prompt_version=provider.prompt_version,
            model_calls_used=session.used,
        )
        ledger.record_decision(conn, run_id, state.get("version_id"), decision)
        status = RunStatus(gate.outcome.value)
        ledger.update_run_status(conn, run_id, status)
        update = {"findings": findings, "gate": gate, "decision": decision, "status": status}
        emit(
            deps,
            {**state, **update},
            STAGE,
            "decision",
            policy_version=policy.POLICY_VERSION,
            final_decision=gate.outcome.value,
            rule_ids=gate.rule_ids,
        )
    return {**update, "timings_ms": {**timings, STAGE: t["duration_ms"]}}
