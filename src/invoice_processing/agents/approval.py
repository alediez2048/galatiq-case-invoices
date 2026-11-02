"""Approval agent: recommend, critique once, revise at most once, then the gate decides.

Deterministic critique checks run alongside the model's critique, so an uncited blocker or
a high-value invoice without threshold scrutiny is flagged even when the model misses it.
Any model failure fails the run before a decision row exists: no `approved` decision is
ever recorded without a complete, successful recommendation loop, and nothing a model
returns can authorize payment.
"""

from decimal import Decimal

from invoice_processing import ledger, policy
from invoice_processing.agents.state import (
    Deps,
    InvoiceState,
    emit,
    emit_model_calls,
    make_session,
)
from invoice_processing.codes import CritiqueIssue, Recommendation, RunStatus, Severity
from invoice_processing.observability import stage_timer
from invoice_processing.reasoning.errors import ModelError
from invoice_processing.reasoning.session import ModelSession
from invoice_processing.schemas import (
    ApprovalDecision,
    ApprovalRecommendation,
    Critique,
    NormalizedInvoice,
    ValidationFinding,
)

STAGE = "approval"
MODEL_FAILED_MESSAGE = "Model request failed. Payment was not attempted."
SUMMARY_CHARS = 300  # audit events keep short summaries only
_CITE_REQUIRED = {Recommendation.approve, Recommendation.review}


def _short(text: str) -> str:
    return text[:SUMMARY_CHARS]


def _mentions_threshold(rec: ApprovalRecommendation, threshold: Decimal) -> bool:
    text = " ".join([rec.summary, *rec.reasons]).lower().replace(",", "")
    return "threshold" in text or f"{threshold:.2f}" in text


def critique_checks(
    invoice: NormalizedInvoice,
    findings: list[ValidationFinding],
    rec: ApprovalRecommendation,
    threshold: Decimal,
) -> list[CritiqueIssue]:
    """Issues the deterministic checks find in a recommendation."""
    issues: list[CritiqueIssue] = []
    blockers = {f.code for f in findings if f.severity is Severity.blocker}
    if rec.recommendation in _CITE_REQUIRED and not blockers <= set(rec.cited_codes):
        issues.append(CritiqueIssue.uncited_blocker)
    total = invoice.stated.total
    if total is not None and total > threshold and not _mentions_threshold(rec, threshold):
        issues.append(CritiqueIssue.missed_high_value_scrutiny)
    return issues


def _merge(model: list[CritiqueIssue], checks: list[CritiqueIssue]) -> list[CritiqueIssue]:
    return list(dict.fromkeys([*model, *checks]))


def _emit_model_calls(deps: Deps, state: InvoiceState, session: ModelSession) -> None:
    emit_model_calls(deps, state, session, STAGE, deps.provider.prompt_version)


def _recommend_loop(
    deps: Deps,
    state: InvoiceState,
    findings: list[ValidationFinding],
    session: ModelSession,
) -> tuple[ApprovalRecommendation, Critique, ApprovalRecommendation | None]:
    """Recommendation, critique (with deterministic issues), and the optional revision."""
    provider, invoice, ctx = deps.provider, state["invoice"], policy.context()
    initial = provider.recommend(invoice, findings, ctx, session)
    emit(
        deps,
        state,
        STAGE,
        "recommendation",
        recommendation=initial.recommendation.value,
        codes=initial.cited_codes,
        summary=_short(initial.summary),
    )
    critique = provider.critique(invoice, findings, initial, ctx, session)
    checks = critique_checks(invoice, findings, initial, ctx.high_value_threshold)
    critique = critique.model_copy(update={"issues": _merge(critique.issues, checks)})
    emit(
        deps,
        state,
        STAGE,
        "critique",
        agrees=critique.agrees,
        issues=[i.value for i in critique.issues],
        omissions=[c.value for c in critique.omissions],
        high_value=critique.high_value,
        revised_recommendation=(
            critique.revised_recommendation.value if critique.revised_recommendation else None
        ),
        summary=_short(critique.summary),
    )
    revised = None
    if not critique.agrees or critique.issues:
        revised = provider.revise(invoice, findings, initial, critique, ctx, session)
        emit(
            deps,
            state,
            STAGE,
            "revision",
            recommendation=revised.recommendation.value,
            codes=revised.cited_codes,
            summary=_short(revised.summary),
        )
    return initial, critique, revised


def _decide(
    deps: Deps,
    state: InvoiceState,
    findings: list[ValidationFinding],
    session: ModelSession,
    loop: tuple[ApprovalRecommendation, Critique, ApprovalRecommendation | None],
) -> dict:
    """Run the deterministic gate on the final recommendation and record the decision."""
    conn, run_id, provider = deps.conn, state["run_id"], deps.provider
    initial, critique, revised = loop
    final = (revised or initial).recommendation
    review = ledger.get_human_review(
        conn, state["invoice_id"], state["version"], policy.POLICY_VERSION
    )
    gate = policy.evaluate(state["invoice"], findings, final, review, version=state["version"])
    ledger.record_findings(conn, run_id, state.get("version_id"), gate.findings)
    decision = ApprovalDecision(
        initial_recommendation=initial.recommendation,
        critique_summary=critique.summary,
        critique_issues=critique.issues,
        revised_recommendation=revised.recommendation if revised else None,
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
    update = {
        "findings": [*findings, *gate.findings],
        "gate": gate,
        "decision": decision,
        "status": status,
        "model_calls_used": session.used,
    }
    emit(
        deps,
        {**state, **update},
        STAGE,
        "decision",
        policy_version=policy.POLICY_VERSION,
        final_decision=gate.outcome.value,
        rule_ids=gate.rule_ids,
    )
    return update


def run(state: InvoiceState, deps: Deps) -> dict:
    timings = state.get("timings_ms", {})
    with stage_timer() as t:
        findings = list(state.get("findings", []))
        ledger.update_run_status(deps.conn, state["run_id"], RunStatus.approval_pending)
        session = make_session(deps, state)
        try:
            loop = _recommend_loop(deps, state, findings, session)
        except ModelError as e:
            # Findings stay recorded; no decision row is written and payment is unreachable.
            _emit_model_calls(deps, state, session)
            update: dict = {
                "status": RunStatus.failed,
                "error_code": e.code.value,
                "error_message": MODEL_FAILED_MESSAGE,
                "model_calls_used": session.used,
            }
            emit(deps, {**state, **update}, STAGE, "model_failed", error_code=e.code.value)
        else:
            _emit_model_calls(deps, state, session)
            update = _decide(deps, state, findings, session, loop)
    return {**update, "timings_ms": {**timings, STAGE: t["duration_ms"]}}
