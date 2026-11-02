from invoice_processing.codes import (
    BUSINESS_OUTCOMES,
    DEFAULT_SEVERITY,
    FINDING_DESCRIPTIONS,
    TERMINAL_RUN_STATUSES,
    C,
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
