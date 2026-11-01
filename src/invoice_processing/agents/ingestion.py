"""Ingestion agent: parse, normalize, and record the invoice version."""

from invoice_processing import ledger
from invoice_processing.agents.state import Deps, InvoiceState, emit
from invoice_processing.codes import DEFAULT_SEVERITY, FindingCode, RunStatus
from invoice_processing.normalize import normalize
from invoice_processing.observability import stage_timer
from invoice_processing.parsers.txt import ExtractionError, parse_txt
from invoice_processing.schemas import ValidationFinding

STAGE = "ingestion"


def run(state: InvoiceState, deps: Deps) -> dict:
    timings = state.get("timings_ms", {})
    with stage_timer() as t:
        try:
            draft = parse_txt(state["source"], state["raw"])
        except ExtractionError as e:
            emit(deps, state, STAGE, "extraction_failed", error_code=e.code)
            update: dict = {"status": RunStatus.failed, "error_code": e.code}
        else:
            invoice, findings = normalize(draft)
            issues = [
                {"code": i.code, "location": ref.location, "snippet": ref.snippet}
                for i in draft.issues
                for ref in i.evidence
            ]
            findings = [
                *findings,
                *(
                    ValidationFinding(
                        code=FindingCode.unparsed_line,
                        severity=DEFAULT_SEVERITY[FindingCode.unparsed_line],
                        evidence=list(i.evidence),
                    )
                    for i in draft.issues
                    if i.code == "unparsed_line"
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
