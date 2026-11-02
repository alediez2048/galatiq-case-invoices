"""Ingestion agent: parse, normalize, and record the invoice version."""

from invoice_processing import ledger, storage
from invoice_processing.agents.state import Deps, InvoiceState, emit
from invoice_processing.codes import DEFAULT_SEVERITY, FindingCode, RunStatus
from invoice_processing.normalize import normalize
from invoice_processing.observability import stage_timer
from invoice_processing.parsers import parse_document
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.schemas import ValidationFinding

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
            if parsed.extracted_text is not None:
                ledger.set_extracted_text(
                    deps.conn, state["source"].source_id, parsed.extracted_text
                )
            invoice, findings = normalize(draft, storage.inventory_items(deps.conn))
            issues = [
                {"code": i.code, "location": ref.location, "snippet": ref.snippet}
                for i in draft.issues
                for ref in i.evidence
            ]
            findings = [
                *findings,
                *(
                    ValidationFinding(
                        code=i.code,
                        severity=DEFAULT_SEVERITY[i.code],
                        evidence=list(i.evidence),
                    )
                    for i in draft.issues
                ),
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
                "invoice": invoice,
                "invoice_id": invoice_id,
                "version_id": version_id,
                "version": version,
                "findings": findings,
                "status": RunStatus.extracted,
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
