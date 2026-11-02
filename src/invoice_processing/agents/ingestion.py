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
MISMATCH_MESSAGE = "The corrected invoice has a different vendor or invoice number."


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
            link = state.get("supersede")
            if link is not None and not _same_identity(deps, link.invoice_id, invoice):
                # Before upsert_invoice: a corrected file for another invoice creates nothing.
                emit(deps, state, STAGE, "corrected_identity_mismatch")
                update = {
                    "status": RunStatus.failed,
                    "error_code": "corrected_identity_mismatch",
                    "error_message": MISMATCH_MESSAGE,
                }
            else:
                update = _record(deps, state, invoice, findings, issues, source_text, calls_used)
    return {**update, "timings_ms": {**timings, STAGE: t["duration_ms"]}}


def _record(
    deps: Deps,
    state: InvoiceState,
    invoice: NormalizedInvoice,
    findings: list[ValidationFinding],
    issues: list[dict],
    source_text: str,
    calls_used: int,
) -> dict:
    """Record the version, check the identity and record the findings; the state update."""
    source = state["source"]
    link = state.get("supersede")
    if link is not None:
        invoice_id = link.invoice_id
    else:
        invoice_id = ledger.upsert_invoice(
            deps.conn, invoice.vendor_key, invoice.invoice_number_key, source.content_hash
        )
    version_id, version = ledger.record_version(
        deps.conn, invoice_id, invoice, source.source_id, supersede=link is not None
    )
    run_id = state["run_id"]
    ledger.attach_run(deps.conn, run_id, invoice_id, version_id)
    identity = ledger.check_identity(
        deps.conn, invoice_id, version_id, run_id, superseding=link is not None
    )
    code = _REVIEW_KINDS.get(identity.kind)
    if code is not None:
        findings.append(
            ValidationFinding(
                code=code, severity=DEFAULT_SEVERITY[code], observed=identity.prior.run_id
            )
        )
    elif link is not None and _is_superseded(deps, version_id):
        # The corrected file matches a version it replaced earlier: an ordinary
        # conflict with the version that is current now (Decision 22).
        code = FindingCode.version_conflict
        findings.append(
            ValidationFinding(
                code=code,
                severity=DEFAULT_SEVERITY[code],
                observed=_current_outcome_run(deps, invoice_id),
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
    return update


def _same_identity(deps: Deps, invoice_id: str, invoice: NormalizedInvoice) -> bool:
    """A corrected submission must carry the identity keys of the invoice it replaces."""
    row = ledger.get_invoice(deps.conn, invoice_id)
    return (invoice.vendor_key, invoice.invoice_number_key) == (
        row.vendor_key,
        row.invoice_number_key,
    )


def _is_superseded(deps: Deps, version_id: str) -> bool:
    return ledger.get_version_by_id(deps.conn, version_id).version_status == "superseded"


def _current_outcome_run(deps: Deps, invoice_id: str) -> str | None:
    """The latest outcome run of the invoice's current version, if any."""
    row = ledger.get_invoice(deps.conn, invoice_id)
    if row.current_version is None:
        return None
    current = ledger.get_version(deps.conn, invoice_id, row.current_version)
    run = ledger.latest_outcome_run(deps.conn, current.version_id)
    return None if run is None else run.run_id


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
