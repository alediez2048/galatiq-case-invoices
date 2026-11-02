"""P4-02: evidence-backed corrections create a new version and revalidate it from scratch."""

import hashlib
import json
from decimal import Decimal

import grpc
import pytest

from invoice_processing import review, service, storage
from invoice_processing.codes import ExecutionMode, ReviewAction, ReviewRefusal, RunStatus
from invoice_processing.reasoning.xai import XaiProvider
from invoice_processing.settings import ConfigurationError, LiveSettings
from tests.fakes.xai_client import FakeXaiClient, Parsed, Raise, factory
from tests.helpers import codes
from tests.review_helpers import (
    EVAL,
    INVOICES,
    REVIEW,
    change,
    correct,
    count,
    payment_count,
    process,
    seeded_db,
)

LIVE = ExecutionMode.live
NOT_IN_SOURCE = (
    "This value is not what the invoice says. Submit a corrected invoice from the vendor."
)
WRONG_PLACE = "The cited location is not where the invoice states this field."
SETTINGS = LiveSettings(api_key="sk-SENTINEL-123", model="grok-test")
UNAVAILABLE = Raise(grpc.StatusCode.UNAVAILABLE)


def counts(db) -> tuple[int, int, int]:
    return (
        count(db, "SELECT COUNT(*) FROM invoice_versions"),
        count(db, "SELECT COUNT(*) FROM corrections"),
        count(db, "SELECT COUNT(*) FROM runs"),
    )


def rows(db, sql, *args) -> list[dict]:
    conn = storage.connect(db)
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def refused(db, result, *changes, **kw) -> review.ReviewRefused:
    before = counts(db)
    with pytest.raises(review.ReviewRefused) as e:
        correct(db, result, *changes, **kw)
    assert counts(db) == before  # a refusal writes nothing
    return e.value


def live_provider(*script) -> XaiProvider:
    return XaiProvider(SETTINGS, factory(FakeXaiClient(list(script))))


def rec() -> dict:
    return {"recommendation": "approve", "reasons": [], "cited_codes": [], "summary": "ok"}


def crit() -> dict:
    return {
        "agrees": True,
        "omissions": [],
        "high_value": False,
        "revised_recommendation": None,
        "summary": "critique agrees",
        "issues": [],
    }


def test_extraction_mistake_corrected_then_paid(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "extraction_mistake.txt", db)
    assert r1.status == "needs_review" and r1.version == 1
    assert "unparseable_value" in codes(r1.findings)
    r2 = correct(db, r1, change("stated.total", "3500.00", "line:13"))  # the Total Amount line
    assert r2.status == "paid_mock" and r2.version == 2
    assert r2.receipt.amount == Decimal("3500.00")
    assert "unparseable_value" not in codes(r2.findings)
    assert "currency_assumed_usd" in codes(r2.findings)  # an uncorrected field's finding carries
    assert payment_count(db, r1.invoice_id) == 1
    assert r2.decision.initial_recommendation is not None  # approval/critique reran
    (v2,) = rows(db, "SELECT * FROM invoice_versions WHERE version = 2")
    assert v2["origin"] == "correction" and v2["parent_version"] == 1
    payload = json.loads(v2["payload_json"])
    assert payload["stated"]["total"] == "3500.00" and payload["computed"] is None
    events = payload["normalization_events"]
    (event,) = [e for e in events if e["provenance"] == "review:correction"]
    assert event["field"] == "stated.total" and event["raw_value"] is None
    assert event["normalized_value"] == "3500.00"
    assert event["evidence"][0]["location"] == "line:13"
    assert event["evidence"][0]["snippet"] == "Total Amount: $3.500,00"
    (v1,) = rows(db, "SELECT version_status FROM invoice_versions WHERE version = 1")
    assert v1["version_status"] == "superseded"


def test_ocr_ambiguous_correction_is_revalidated_not_cleared(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "ocr_ambiguous.txt", db)
    assert r1.status == "needs_review" and "ambiguous_normalization" in codes(r1.findings)
    e = refused(db, r1, change("lines[0].line_total", "3150.00", "line:9"))
    assert e.code is ReviewRefusal.correction_not_in_source
    r2 = correct(db, r1, change("lines[0].line_total", "3500.00", "line:9"))
    assert r2.status == "rejected" and r2.version == 2
    assert "line_total_mismatch" in codes(r2.findings)
    assert "ambiguous_normalization" not in codes(r2.findings)
    assert payment_count(db, r1.invoice_id) == 0


def test_inv_1013_total_correction_refused(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(INVOICES / "invoice_1013.json", db)
    assert r1.status == "rejected"
    e = refused(db, r1, change("stated.total", "22512.80", "$.total"))
    assert e.code is ReviewRefusal.correction_not_in_source
    assert e.message == NOT_IN_SOURCE
    assert e.current.current_version == 1 and e.current.status == "rejected"


def test_source_error_cannot_cite_subtotal(tmp_path):  # Review Focus 1
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "source_error.json", db)
    assert r1.status == "rejected" and "total_mismatch" in codes(r1.findings)
    e = refused(db, r1, change("stated.total", "5000.00", "$.subtotal"))
    assert e.code is ReviewRefusal.evidence_location_mismatch and e.message == WRONG_PLACE
    e = refused(db, r1, change("stated.total", "5000.00", "$.total"))
    assert e.code is ReviewRefusal.correction_not_in_source
    e = refused(db, r1, change("stated.total", "5000.00", "$.nowhere"))
    assert e.code is ReviewRefusal.evidence_location_mismatch


def test_stale_expected_version_writes_nothing(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "ocr_ambiguous.txt", db)
    correct(db, r1, change("lines[0].line_total", "3500.00", "line:9"))
    e = refused(db, r1, change("lines[0].quantity", "7", "line:9"), expected_version=1)
    assert e.code is ReviewRefusal.stale_version
    assert e.current.current_version == 2


def test_source_bytes_and_v1_payload_unchanged(tmp_path):
    db = seeded_db(tmp_path)
    path = REVIEW / "extraction_mistake.txt"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    r1 = process(path, db)
    sources = rows(db, "SELECT * FROM sources")
    v1 = rows(db, "SELECT payload_json, semantic_hash FROM invoice_versions WHERE version = 1")
    assert sources[0]["extracted_text"] == path.read_text()  # persisted for every format
    correct(db, r1, change("stated.total", "3500.00", "line:13"))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert rows(db, "SELECT * FROM sources") == sources
    after = rows(db, "SELECT payload_json, semantic_hash FROM invoice_versions WHERE version = 1")
    assert after == v1


def test_all_or_nothing_multi_field(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "extraction_mistake.txt", db)
    e = refused(
        db,
        r1,
        change("stated.total", "3500.00", "line:13"),
        change("lines[0].quantity", "8", "line:9"),  # the line says 7
    )
    assert e.code is ReviewRefusal.correction_not_in_source


def test_invalid_value_and_line_index(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "extraction_mistake.txt", db)
    e = refused(db, r1, change("stated.total", "three thousand", "line:13"))
    assert e.code is ReviewRefusal.invalid_value
    e = refused(db, r1, change("due_date", "01/03/2026", "line:6"))
    assert e.code is ReviewRefusal.invalid_value
    e = refused(db, r1, change("lines[3].quantity", "7", "line:9"))
    assert e.code is ReviewRefusal.field_not_correctable


def test_paid_invoice_correction_refused(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(INVOICES / "invoice_1001.txt", db)
    assert r1.status == "paid_mock"
    e = refused(db, r1, change("stated.total", "5000.00", "line:14"))
    assert e.code is ReviewRefusal.already_paid


def test_identity_change_refused(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "extraction_mistake.txt", db)
    e = refused(db, r1, change("invoice_number", "CT-9999", "line:4"))
    assert e.code is ReviewRefusal.identity_correction_deferred
    e = refused(db, r1, change("vendor", "Other Vendor", "line:3"))
    assert e.code is ReviewRefusal.identity_correction_deferred


def test_explicit_eur_currency_not_correctable(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(INVOICES / "invoice_1014.xml", db)
    assert r1.status == "needs_review"
    e = refused(db, r1, change("currency", "USD", "/invoice/header/currency"))
    assert e.code is ReviewRefusal.field_not_correctable


def test_unknown_invoice_refused(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "extraction_mistake.txt", db)
    ghost = r1.model_copy(update={"invoice_id": "inv-nope"})
    e = refused(db, ghost, change("stated.total", "3500.00", "line:13"))
    assert e.code is ReviewRefusal.unknown_invoice and e.current is None


def test_correction_audit_and_links(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(REVIEW / "extraction_mistake.txt", db)
    r2 = correct(db, r1, change("stated.total", "3500.00", "line:13"))
    (row,) = rows(db, "SELECT * FROM corrections")
    assert row["run_id"] == r2.run_id and row["reviewer"] == "Ana"
    assert (row["from_version"], row["to_version"]) == (1, 2)
    assert (row["field"], row["old_value"], row["new_value"]) == ("stated.total", None, "3500.00")
    assert row["evidence_location"] == "line:13" and row["reason"] == "Misread total"
    (run,) = rows(db, "SELECT * FROM runs WHERE run_id = ?", r2.run_id)
    assert run["trigger"] == "correction" and run["review_of"] == r1.run_id
    assert run["evaluation_date"] == EVAL.isoformat() and run["mode"] == "offline"
    events = rows(db, "SELECT event, actor, payload_json FROM audit_events WHERE actor IS NOT NULL")
    by_name = {e["event"]: e for e in events}
    assert {"correction_applied", "approvals_invalidated"} <= set(by_name)
    assert {e["actor"] for e in events} == {"Ana"}
    applied = json.loads(by_name["correction_applied"]["payload_json"])
    assert applied["fields"] == ["stated.total"]
    invalidated = json.loads(by_name["approvals_invalidated"]["payload_json"])
    assert invalidated == {
        "superseded_version": 1,
        "decision_run_ids": [r1.run_id],
        "human_review_ids": [],
    }


def test_allowed_actions_table(tmp_path):
    db = seeded_db(tmp_path)
    needs = process(REVIEW / "extraction_mistake.txt", db)
    a = review.allowed_actions(needs.invoice_id, db_path=db)
    assert a.allowed == [ReviewAction.correct, ReviewAction.submit_corrected]
    assert a.refused == {
        ReviewAction.approve: ReviewRefusal.action_not_allowed,
        ReviewAction.decline: ReviewRefusal.action_not_allowed,
    }
    paid = process(INVOICES / "invoice_1001.txt", db)
    a = review.allowed_actions(paid.invoice_id, db_path=db)
    assert a.allowed == [] and set(a.refused.values()) == {ReviewRefusal.already_paid}
    with pytest.raises(review.ReviewRefused) as e:
        review.allowed_actions("inv-nope", db_path=db)
    assert e.value.code is ReviewRefusal.unknown_invoice


def test_live_correction_without_credentials_writes_nothing(tmp_path):  # Review Focus 5
    db = seeded_db(tmp_path)
    base = live_provider(Parsed({"proposals": []}), Parsed(rec()), Parsed(crit()))
    r1 = process(REVIEW / "extraction_mistake.txt", db, mode=LIVE, provider=base)
    assert r1.status == "needs_review" and r1.mode is LIVE
    before = counts(db)
    with pytest.raises(ConfigurationError):
        correct(db, r1, change("stated.total", "3500.00", "line:13"))  # no XAI_* env
    assert counts(db) == before


def test_failed_live_correction_retried_on_same_version(tmp_path):
    db = seeded_db(tmp_path)
    base = live_provider(Parsed({"proposals": []}), Parsed(rec()), Parsed(crit()))
    r1 = process(REVIEW / "extraction_mistake.txt", db, mode=LIVE, provider=base)
    r2 = correct(
        db,
        r1,
        change("stated.total", "3500.00", "line:13"),
        provider=live_provider(UNAVAILABLE, UNAVAILABLE),
    )
    assert r2.status is RunStatus.failed and r2.recoverable and r2.version == 2
    assert payment_count(db, r1.invoice_id) == 0
    r3 = service.retry_run(
        r2.run_id, None, db, EVAL, provider=live_provider(Parsed(rec()), Parsed(crit()))
    )
    assert r3.status == "paid_mock" and r3.version == 2 and r3.mode is LIVE
    (run,) = rows(db, "SELECT * FROM runs WHERE run_id = ?", r3.run_id)
    assert run["retry_of"] == r2.run_id and run["trigger"] == "correction"
    assert run["review_of"] == r1.run_id
    assert payment_count(db, r1.invoice_id) == 1
    assert count(db, "SELECT COUNT(*) FROM invoice_versions") == 2  # no re-extraction
    with pytest.raises(service.RetryRefused) as e:
        service.retry_run(r3.run_id, None, db, EVAL)
    assert e.value.reason == "not_failed"


def test_run_existing_version_human_approval_not_yet_available(tmp_path):
    db = seeded_db(tmp_path)
    with pytest.raises(NotImplementedError):
        service.run_existing_version("run-any", db_path=db, approval="human")


def test_submission_retry_still_needs_its_file(tmp_path):
    db = seeded_db(tmp_path)
    failed = process(
        REVIEW / "extraction_mistake.txt",
        db,
        mode=LIVE,
        provider=live_provider(Parsed({"proposals": []}), UNAVAILABLE, UNAVAILABLE),
    )
    assert failed.status is RunStatus.failed and failed.recoverable
    with pytest.raises(ValueError):
        service.retry_run(failed.run_id, None, db, EVAL)
    assert count(db, "SELECT COUNT(*) FROM runs") == 1
