"""Ingestion agent: parse, normalize, and record the invoice version.

In live mode a draft with review-or-worse extraction problems gets one evidence-checked
model assist step (plus at most one repair) before the version is recorded.
"""

from collections.abc import Collection

from invoice_processing import assist, ledger, storage
from invoice_processing.agents.state import (
    Deps,
    InvoiceState,
    emit,
    emit_model_calls,
    make_session,
)
from invoice_processing.codes import (
    DEFAULT_SEVERITY,
    ExecutionMode,
    FindingCode,
    ModelErrorCode,
    RunStatus,
)
from invoice_processing.normalize import normalize
from invoice_processing.observability import stage_timer
from invoice_processing.parsers import parse_document
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.reasoning.errors import ModelError
from invoice_processing.schemas import InvoiceDraft, NormalizedInvoice, ValidationFinding

STAGE = "ingestion"
# Identity checks that continue to validation; the gate's review rule decides the outcome.
_REVIEW_KINDS = {
    "revision_after_payment": FindingCode.revision_after_payment,
    "version_conflict": FindingCode.version_conflict,
}


def run(state: InvoiceState, deps: Deps) -> dict:
    timings = state.get("timings_ms", {})
    with stage_timer() as t:
        try:
            parsed = parse_document(state["source"], state["raw"], deps.limits)
            draft = parsed.draft
            if len(draft.lines) > deps.limits.max_lines:
                raise ExtractionError(
                    "too_many_lines",
                    f"The invoice has {len(draft.lines)} lines; the limit is "
                    f"{deps.limits.max_lines}.",
                )
        except ExtractionError as e:
            emit(deps, state, STAGE, "extraction_failed", error_code=e.code)
            update: dict = {
                "status": RunStatus.failed,
                "error_code": e.code,
                "error_message": str(e),
            }
        else:
            source_text = parsed.extracted_text
            if source_text is None:
                source_text = state["raw"].decode("utf-8-sig", errors="replace")
            # Kept for every format (only while unset) so review corrections can check
            # their cited evidence against the text this version was read from.
            ledger.set_extracted_text(deps.conn, state["source"].source_id, source_text)
            known = storage.inventory_items(deps.conn)
            invoice, findings = _normalize(draft, known)
            calls_used = state.get("model_calls_used", 0)
            if deps.provider.mode is ExecutionMode.live and assist.needs_assist(draft, findings):
                draft, assist_findings, calls_used = _assist(
                    deps, state, draft, findings, source_text, known
                )
                invoice, findings = _normalize(draft, known)  # re-run on the amended draft
                findings += assist_findings
            issues = [
                {"code": i.code, "location": ref.location, "snippet": ref.snippet}
                for i in draft.issues
                for ref in i.evidence
            ]
            source = state["source"]
            invoice_id = ledger.upsert_invoice(
                deps.conn, invoice.vendor_key, invoice.invoice_number_key, source.content_hash
            )
            version_id, version = ledger.record_version(
                deps.conn, invoice_id, invoice, source.source_id
            )
            run_id = state["run_id"]
            ledger.attach_run(deps.conn, run_id, invoice_id, version_id)
            identity = ledger.check_identity(deps.conn, invoice_id, version_id, run_id)
            code = _REVIEW_KINDS.get(identity.kind)
            if code is not None:
                findings.append(
                    ValidationFinding(
                        code=code, severity=DEFAULT_SEVERITY[code], observed=identity.prior.run_id
                    )
                )
            ledger.record_findings(deps.conn, run_id, version_id, findings)
            ledger.update_run_status(deps.conn, run_id, RunStatus.extracted)
            update = {
                "source_text": source_text,
                "invoice": invoice,
                "invoice_id": invoice_id,
                "version_id": version_id,
                "version": version,
                "findings": findings,
                "status": RunStatus.extracted,
                "model_calls_used": calls_used,
            }
            emit(
                deps,
                {**state, **update},
                STAGE,
                "extracted",
                source_hash=source.content_hash,
                version=version,
                codes=[f.code for f in findings],
                issues=issues,
            )
            if identity.kind == "duplicate":
                prior = identity.prior
                ledger.update_run_status(deps.conn, run_id, RunStatus.duplicate)
                update = {
                    **update,
                    "status": RunStatus.duplicate,
                    "prior_run_id": prior.run_id,
                    "receipt": prior.receipt,
                }
                emit(
                    deps,
                    {**state, **update},
                    STAGE,
                    "duplicate",
                    prior_run_id=prior.run_id,
                    prior_status=prior.status.value,
                    match="semantic",
                )
    return {**update, "timings_ms": {**timings, STAGE: t["duration_ms"]}}


def _normalize(
    draft: InvoiceDraft, known: Collection[str]
) -> tuple[NormalizedInvoice, list[ValidationFinding]]:
    """Normalization findings plus one finding per extraction issue."""
    invoice, findings = normalize(draft, known)
    findings += [
        ValidationFinding(code=i.code, severity=DEFAULT_SEVERITY[i.code], evidence=list(i.evidence))
        for i in draft.issues
    ]
    return invoice, findings


def _assist(
    deps: Deps,
    state: InvoiceState,
    draft: InvoiceDraft,
    findings: list[ValidationFinding],
    source_text: str,
    known: Collection[str],
) -> tuple[InvoiceDraft, list[ValidationFinding], int]:
    """Live extraction assist: one step plus at most one repair; never fails the run.

    Returns the (possibly amended) draft, the assist findings and the budget units used.
    Any model failure leaves the draft unchanged, so the original issues stay unresolved
    and route through validation and the gate as usual.
    """
    provider = deps.provider
    session = make_session(deps, {**state, "source_text": source_text})
    request = assist.build_request(
        draft, findings, source_text, state["source"].format, known, provider.excerpt_chars
    )
    prompt_version = provider.extract_prompt_version
    repaired = False
    try:
        try:
            result = provider.assist_extraction(request, session)
        except ModelError as e:
            if e.code is not ModelErrorCode.model_output_invalid:
                raise
            repaired = True  # same excerpts; only the hint is added
            repair = request.model_copy(update={"repair_hint": e.message})
            result = provider.assist_extraction(repair, session)
    except ModelError as e:
        emit_model_calls(deps, state, session, STAGE, prompt_version)
        emit(deps, state, STAGE, "assist_failed", error_code=e.code.value, repaired=repaired)
        return draft, [], session.used
    emit_model_calls(deps, state, session, STAGE, prompt_version)
    source_lines = {e.location: e.text for e in request.excerpts}
    provenance = f"model:{provider.provider}/{provider.model}"
    amended, extra, accepted = assist.apply(draft, result.proposals, source_lines, provenance)
    emit(
        deps,
        state,
        STAGE,
        "assist",
        repaired=repaired,
        proposals=len(result.proposals),
        accepted=accepted,
        codes=[f.code for f in extra],
    )
    return amended, extra, session.used
