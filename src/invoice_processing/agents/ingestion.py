"""Ingestion agent: parse, normalize, and record the invoice version."""

from invoice_processing import ledger, storage
from invoice_processing.agents.state import Deps, InvoiceState, emit
from invoice_processing.codes import DEFAULT_SEVERITY, RunStatus
from invoice_processing.normalize import normalize
from invoice_processing.observability import stage_timer
from invoice_processing.parsers import parse_document
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.schemas import ValidationFinding

STAGE = "ingestion"


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
            ledger.record_findings(deps.conn, run_id, version_id, findings)
            ledger.attach_run(deps.conn, run_id, invoice_id, version_id)
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
    return {**update, "timings_ms": {**timings, STAGE: t["duration_ms"]}}
