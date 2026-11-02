from invoice_processing.codes import (
    BUSINESS_OUTCOMES,
    DEFAULT_SEVERITY,
    FINDING_DESCRIPTIONS,
    TERMINAL_RUN_STATUSES,
    C,
    ExecutionMode,
    FindingCode,
    InvoiceStatus,
    RunStatus,
    Severity,
)


def test_every_code_has_description_and_severity():
    for code in FindingCode:
        assert FINDING_DESCRIPTIONS[code].strip()
        assert DEFAULT_SEVERITY[code] in Severity


def test_duplicate_is_run_only_and_superseded_is_invoice_only():
    assert "duplicate" in RunStatus.__members__
    assert "duplicate" not in InvoiceStatus.__members__
    assert "superseded" in InvoiceStatus.__members__
    assert "superseded" not in RunStatus.__members__


def test_codes_are_strings():
    assert FindingCode.total_mismatch == "total_mismatch"
    assert str(Severity.blocker) == "blocker"


def test_phase1_codes_and_severities():
    assert DEFAULT_SEVERITY[C.currency_assumed_usd] is Severity.info
    assert DEFAULT_SEVERITY[C.model_disagreement] is Severity.warning
    assert DEFAULT_SEVERITY[C.non_usd_currency] is Severity.review
    assert set(FINDING_DESCRIPTIONS) == set(FindingCode)
    assert BUSINESS_OUTCOMES < TERMINAL_RUN_STATUSES
    assert RunStatus.failed not in BUSINESS_OUTCOMES


PHASE2 = {
    "ambiguous_normalization": Severity.review,
    "unparseable_value": Severity.review,
    "risk_signal_urgency": Severity.info,
    "due_date_unresolved": Severity.review,
    "ambiguous_date": Severity.review,
    "due_before_invoice_date": Severity.warning,
    "terms_inconsistent": Severity.warning,
    "unsupported_currency": Severity.review,
    "currency_conflict": Severity.review,
    "revision_after_payment": Severity.review,
    "version_conflict": Severity.review,
    "unrecognized_field": Severity.info,
    "duplicate_field": Severity.review,
    "malformed_row": Severity.review,
    "inconsistent_row_header": Severity.blocker,
}


def test_phase2_codes_and_severities():
    for name, severity in PHASE2.items():
        code = FindingCode(name)
        assert DEFAULT_SEVERITY[code] is severity
        assert FINDING_DESCRIPTIONS[code]


def _codes_named_in(module: str) -> set[FindingCode]:
    import re
    from pathlib import Path

    import invoice_processing

    text = (Path(invoice_processing.__file__).parent / module).read_text()
    names = set(re.findall(r"\b(?:C|FindingCode)\.([a-z_]+)", text))
    return {FindingCode(n) for n in names}


def test_code_stage_sets_partition_all_codes():
    from invoice_processing.codes import GATE_CODES, INGESTION_CODES, VALIDATION_CODES

    sets = [VALIDATION_CODES, GATE_CODES, INGESTION_CODES]
    assert all(a.isdisjoint(b) for i, a in enumerate(sets) for b in sets[i + 1 :])
    assert VALIDATION_CODES | GATE_CODES | INGESTION_CODES == set(FindingCode)
    assert GATE_CODES == {C.model_disagreement, C.non_usd_currency, C.human_declined}


def test_stage_sets_match_the_modules_that_emit_them():
    # A new validation or gate code must be added to its set, or it would be carried
    # forward by a review run as if ingestion had found it.
    from invoice_processing.codes import GATE_CODES, VALIDATION_CODES

    assert _codes_named_in("validation.py") == VALIDATION_CODES
    assert _codes_named_in("policy.py") <= GATE_CODES


def test_extraction_review_codes_are_ingestion_review_codes():
    from invoice_processing.codes import EXTRACTION_REVIEW_CODES, INGESTION_CODES

    assert EXTRACTION_REVIEW_CODES == {
        C.ambiguous_normalization,
        C.unparseable_value,
        C.ambiguous_date,
        C.due_date_unresolved,
        C.duplicate_field,
        C.malformed_row,
        C.model_parser_disagreement,
    }
    assert EXTRACTION_REVIEW_CODES <= INGESTION_CODES
    assert all(DEFAULT_SEVERITY[c] is Severity.review for c in EXTRACTION_REVIEW_CODES)


def test_human_declined_is_blocker():
    assert DEFAULT_SEVERITY[C.human_declined] is Severity.blocker
    assert FINDING_DESCRIPTIONS[C.human_declined] == "A human reviewer declined this version."


def test_review_enums():
    from invoice_processing.codes import QueueGroup, ReviewAction, ReviewRefusal

    assert [a.value for a in ReviewAction] == ["correct", "approve", "decline", "submit_corrected"]
    assert [g.value for g in QueueGroup] == [
        "correctable_extraction",
        "awaiting_human_approval",
        "unresolved_blocker",
    ]
    assert {r.value for r in ReviewRefusal} == {
        "unknown_invoice",
        "stale_version",
        "action_not_allowed",
        "already_paid",
        "field_not_correctable",
        "identity_correction_deferred",
        "invalid_value",
        "correction_not_in_source",
        "evidence_location_mismatch",
        "evidence_unavailable",
        "source_text_unavailable",
        "corrected_identity_mismatch",
    }


def test_corpus_findings_respect_stage_sets(tmp_path, monkeypatch):
    # Decision 12: a review run carries ingestion-stage findings and recomputes the rest, so
    # every code a stage records must belong to that stage's set.
    from datetime import date
    from pathlib import Path

    from invoice_processing import policy, seed, storage
    from invoice_processing.agents import validation as validation_node
    from invoice_processing.codes import GATE_CODES, INGESTION_CODES, VALIDATION_CODES
    from invoice_processing.service import process_invoice

    seen = {"ingestion": set(), "validation": set(), "gate": set()}
    real_validation, real_evaluate = validation_node.run, policy.evaluate

    def spy_validation(state, deps):
        earlier = state.get("findings", [])
        update = real_validation(state, deps)
        seen["ingestion"] |= {f.code for f in earlier}
        seen["validation"] |= {f.code for f in update["findings"][len(earlier) :]}
        return update

    def spy_evaluate(*args, **kwargs):
        gate = real_evaluate(*args, **kwargs)
        seen["gate"] |= {f.code for f in gate.findings}
        return gate

    monkeypatch.setattr(validation_node, "run", spy_validation)
    monkeypatch.setattr(policy, "evaluate", spy_evaluate)
    files = sorted(Path("data/invoices").iterdir())
    for i, path in enumerate(files):
        db = tmp_path / f"{i}.db"
        conn = storage.connect(db)
        storage.init_schema(conn)
        seed.seed_inventory(conn)
        conn.close()
        process_invoice(path, ExecutionMode.offline, db, date(2026, 1, 31))
    assert seen["validation"] and seen["gate"]  # the spies saw the corpus
    assert seen["ingestion"] <= INGESTION_CODES
    assert seen["validation"] <= VALIDATION_CODES
    assert seen["gate"] <= GATE_CODES
