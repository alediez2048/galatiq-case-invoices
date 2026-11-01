from invoice_processing.codes import (
    DEFAULT_SEVERITY,
    FINDING_DESCRIPTIONS,
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
