"""P5-04 review action endpoints: TestClient against a fresh temporary database per test.

Invoices are processed with the service directly (the review fixtures live outside the
bundled samples), then corrected over HTTP. Offline, except where a fake xAI client stands in
for the live provider (sentinel key, no network)."""

import uuid
from pathlib import Path

import grpc
import pytest
from fastapi.testclient import TestClient

from invoice_processing import api, storage
from invoice_processing.codes import ExecutionMode
from invoice_processing.reasoning import xai
from tests.fakes.xai_client import FakeXaiClient, Parsed, Raise
from tests.review_helpers import EVAL, INVOICES, REVIEW, process
from tests.test_api import TEST_HOSTS, wait_done

SENTINEL = "sk-SENTINEL-p504"
LIVE = ExecutionMode.live
NOT_IN_SOURCE = (
    "This value is not what the invoice says. Submit a corrected invoice from the vendor."
)
WRONG_PLACE = "The cited location is not where the invoice states this field."
DOWN = Raise(grpc.StatusCode.UNAVAILABLE)
TABLES = ("invoice_versions", "corrections", "runs", "audit_events", "findings", "payments")


@pytest.fixture
def settings(tmp_path) -> api.ApiSettings:
    s = api.ApiSettings(
        db_path=tmp_path / "api.db",
        uploads_dir=tmp_path / "uploads",
        samples_dir=INVOICES,
        frontend_dist=tmp_path / "no-dist",
        evaluation_date=EVAL,
    )
    s.allowed_hosts = TEST_HOSTS
    return s


@pytest.fixture
def client(settings):
    with TestClient(api.create_app(settings)) as c:
        yield c


def counts(settings) -> dict[str, int]:
    conn = storage.connect(settings.db_path)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        conn.close()


def rows(settings, sql, *args) -> list[dict]:
    conn = storage.connect(settings.db_path)
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def body(field="stated.total", value="3500.00", loc="line:13", version=1, **extra) -> dict:
    return {
        "expected_version": version,
        "changes": [{"field": field, "new_value": value, "evidence_location": loc}],
        "reason": "Misread total",
        "reviewer": "Ana",
        **extra,
    }


def correct(client, invoice_id, payload, key="key-1"):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"/api/invoices/{invoice_id}/corrections", json=payload, headers=headers)


def finished(client, r, status=202) -> dict:
    """The accepted action's run once finished; its ProcessingResult."""
    assert r.status_code == status, r.text
    accepted = r.json()
    assert set(accepted) == {"run_id", "status", "mode", "idempotent_replay"}
    return wait_done(client, accepted["run_id"])["result"]


def refused(client, settings, invoice_id, payload, status, code, key="key-1") -> dict:
    before = counts(settings)
    r = correct(client, invoice_id, payload, key=key)
    assert r.status_code == status, r.text
    err = r.json()
    assert err["code"] == code
    assert counts(settings) == before  # a refusal writes nothing
    return err


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


@pytest.fixture
def live(monkeypatch):
    """Live settings with a sentinel key; each xAI client takes the next script."""
    scripts: list[list] = []
    monkeypatch.setenv("XAI_API_KEY", SENTINEL)
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    monkeypatch.setattr(xai, "real_client_factory", lambda s: FakeXaiClient(scripts.pop(0)))
    return scripts


def live_needs_review(settings, live) -> str:
    """extraction_mistake.txt processed live (needs_review, version 1); its invoice id."""
    live.append([Parsed({"proposals": []}), Parsed(rec()), Parsed(crit())])
    r1 = process(REVIEW / "extraction_mistake.txt", settings.db_path, mode=LIVE)
    assert r1.status == "needs_review" and r1.mode is LIVE, r1
    return r1.invoice_id


# ------------------------------------------------------------------ corrections


def test_correction_creates_a_version_and_returns_the_revalidation_run(client, settings):
    r1 = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    r = correct(client, r1.invoice_id, body())
    assert r.json()["idempotent_replay"] is False
    result = finished(client, r)
    assert result["status"] == "paid_mock" and result["version"] == 2
    assert result["run_id"] != r1.run_id and result["invoice_id"] == r1.invoice_id
    assert result["receipt"]["amount"] == "3500.00"
    run = client.get(f"/api/runs/{result['run_id']}").json()
    assert run["terminal"] and run["status"] == "paid_mock"
    detail = client.get(f"/api/invoices/{r1.invoice_id}").json()
    assert detail["current_version"] == 2 and detail["outcome"] == "paid_mock"
    (c,) = detail["corrections"]
    assert (c["field"], c["new_value"], c["reviewer"]) == ("stated.total", "3500.00", "Ana")
    sql = "SELECT trigger, review_of FROM runs WHERE run_id = ?"
    (stored,) = rows(settings, sql, run["run_id"])
    assert stored == {"trigger": "correction", "review_of": r1.run_id}


def test_repeated_key_replays_the_original_response_once(client, settings):
    r1 = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    first = correct(client, r1.invoice_id, body(), key="same")
    finished(client, first)
    after_first = counts(settings)
    again = correct(client, r1.invoice_id, body(), key="same")
    assert again.status_code == 202
    assert again.json()["run_id"] == first.json()["run_id"]
    assert again.json()["idempotent_replay"] is True
    assert counts(settings) == after_first  # no second version, run or payment
    assert after_first["payments"] == 1 and after_first["corrections"] == 1


def test_repeated_key_with_a_different_body_is_refused(client, settings):
    r1 = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    finished(client, correct(client, r1.invoice_id, body(), key="same"))
    changed = body(reason="Another reason")
    err = refused(
        client, settings, r1.invoice_id, changed, 422, "idempotency_key_reused", key="same"
    )
    assert err["message"] == "This Idempotency-Key was already used for a different request."


def test_a_key_is_scoped_to_its_invoice(client, settings):
    a = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    b = process(INVOICES / "invoice_1001.txt", settings.db_path)
    finished(client, correct(client, a.invoice_id, body(), key="k"))
    r = correct(client, b.invoice_id, body(loc="line:14"), key="k")
    assert r.status_code == 409 and r.json()["code"] == "already_paid"  # not a replay of a


def test_idempotency_key_is_required(client, settings):
    r1 = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    before = counts(settings)
    r = correct(client, r1.invoice_id, body(), key=None)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert any(d["loc"] == ["header", "idempotency-key"] for d in r.json()["details"])
    assert counts(settings) == before


@pytest.mark.parametrize(
    "payload",
    [
        {k: v for k, v in body().items() if k != "reason"},
        {k: v for k, v in body().items() if k != "reviewer"},
        {k: v for k, v in body().items() if k != "expected_version"},
        body(reason="   "),
        body(version=0),
        body(changes=[]),
        body(field="vendor_key"),
        body(extra_field=1),
    ],
)
def test_malformed_body_is_a_validation_error(client, settings, payload):
    r1 = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    refused(client, settings, r1.invoice_id, payload, 422, "validation_error")


def test_duplicate_fields_are_a_validation_error(client, settings):
    r1 = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    change = {"field": "stated.total", "new_value": "3500.00", "evidence_location": "line:13"}
    payload = body(changes=[change, change])
    err = refused(client, settings, r1.invoice_id, payload, 422, "validation_error")
    assert "at most once" in str(err["details"])


def test_stale_version_is_409_with_the_current_record(client, settings):
    r1 = process(REVIEW / "ocr_ambiguous.txt", settings.db_path)
    line_total = body(field="lines[0].line_total", value="3500.00", loc="line:9")
    assert finished(client, correct(client, r1.invoice_id, line_total))["status"] == "rejected"
    before = counts(settings)
    r = correct(client, r1.invoice_id, line_total, key="second")  # still says version 1
    assert r.status_code == 409
    err = r.json()
    assert err["code"] == "stale_version"
    current, invoice = err["details"]["current"], err["details"]["invoice"]
    assert current["current_version"] == 2 and current["invoice_id"] == r1.invoice_id
    assert invoice == client.get(f"/api/invoices/{r1.invoice_id}").json()
    assert invoice["current_version"] == 2 and invoice["review_actions"] == current
    assert counts(settings) == before


def test_already_paid_is_409_with_the_current_record(client, settings):
    paid = process(INVOICES / "invoice_1001.txt", settings.db_path)
    err = refused(client, settings, paid.invoice_id, body(loc="line:14"), 409, "already_paid")
    assert err["details"]["current"]["allowed"] == []
    assert err["details"]["invoice"]["outcome"] == "paid_mock"


def test_correction_on_a_failed_invoice_is_409_action_not_allowed(client, settings, live):
    live.append([Parsed({"proposals": []}), DOWN, DOWN])
    failed = process(REVIEW / "extraction_mistake.txt", settings.db_path, mode=LIVE)
    assert failed.status == "failed" and failed.invoice_id, failed
    err = refused(client, settings, failed.invoice_id, body(), 409, "action_not_allowed")
    assert "correct" not in err["details"]["current"]["allowed"]
    assert err["details"]["invoice"]["invoice_id"] == failed.invoice_id


def test_unknown_invoice_is_404(client, settings):
    err = refused(client, settings, "inv-nope", body(), 404, "unknown_invoice")
    assert err["details"] == {"current": None}


def test_correction_not_in_source_is_422_with_the_guidance(client, settings):
    r1 = process(INVOICES / "invoice_1013.json", settings.db_path)
    payload = body(value="22512.80", loc="$.total")
    err = refused(client, settings, r1.invoice_id, payload, 422, "correction_not_in_source")
    assert err["message"] == NOT_IN_SOURCE
    assert err["details"]["current"]["current_version"] == 1
    assert "invoice" not in err["details"]


@pytest.mark.parametrize("loc", ["$.subtotal", "$.nowhere", "line:14"])
def test_evidence_location_mismatch_is_422(client, settings, loc):
    r1 = process(REVIEW / "source_error.json", settings.db_path)
    payload = body(value="5000.00", loc=loc)
    err = refused(client, settings, r1.invoice_id, payload, 422, "evidence_location_mismatch")
    assert err["message"] == WRONG_PLACE


@pytest.mark.parametrize(
    "field,value,loc,code",
    [
        ("stated.total", "three thousand", "line:13", "invalid_value"),
        ("lines[3].quantity", "7", "line:9", "field_not_correctable"),
        ("invoice_number", "CT-9999", "line:4", "identity_correction_deferred"),
    ],
)
def test_other_refusals_are_422_with_their_code(client, settings, field, value, loc, code):
    r1 = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    refused(client, settings, r1.invoice_id, body(field=field, value=value, loc=loc), 422, code)


def test_live_correction_without_credentials_is_provider_unavailable(
    client, settings, live, monkeypatch
):
    invoice_id = live_needs_review(settings, live)
    monkeypatch.delenv("XAI_API_KEY")
    err = refused(client, settings, invoice_id, body(), 409, "provider_unavailable")
    assert "XAI_API_KEY" in err["message"]


def test_busy_when_another_job_holds_the_processing_lock(client, settings):
    r1 = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    settings.run_start_timeout_s = 0.05
    with api.PROCESSING_LOCK:
        r = correct(client, r1.invoice_id, body())
    assert r.status_code == 503 and r.json()["code"] == "busy"
    finished(client, correct(client, r1.invoice_id, body()))  # nothing was stored


# ------------------------------------------------------------------ allowed actions


def test_detail_carries_the_review_actions(client, settings):
    needs = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    actions = client.get(f"/api/invoices/{needs.invoice_id}").json()["review_actions"]
    assert actions == {
        "invoice_id": needs.invoice_id,
        "status": "needs_review",
        "current_version": 1,
        "allowed": ["correct", "submit_corrected"],
        "refused": {"approve": "action_not_allowed", "decline": "action_not_allowed"},
    }
    paid = process(INVOICES / "invoice_1001.txt", settings.db_path)
    detail = client.get(f"/api/invoices/{paid.invoice_id}").json()
    assert detail["review_actions"]["allowed"] == []
    assert set(detail["review_actions"]["refused"].values()) == {"already_paid"}
    assert detail["allowed_actions"] == []  # run-level actions stay separate


# ------------------------------------------------------------------ retry of a correction run


def failed_correction(client, settings, live) -> tuple[str, dict]:
    invoice_id = live_needs_review(settings, live)
    live.append([DOWN, DOWN])
    result = finished(client, correct(client, invoice_id, body()))
    assert result["status"] == "failed" and result["recoverable"] and result["version"] == 2
    return invoice_id, result


def retry(client, run_id, key=None, **payload):
    headers = {"Idempotency-Key": key or str(uuid.uuid4())}
    return client.post(f"/api/runs/{run_id}/retry", json=payload or None, headers=headers)


def test_failed_correction_run_is_retried_without_its_file(client, settings, live):
    invoice_id, failed = failed_correction(client, settings, live)
    # The review fixture is not a bundled sample or an upload: no original file exists.
    assert not (Path(settings.samples_dir) / "extraction_mistake.txt").exists()
    live.append([Parsed(rec()), Parsed(crit())])
    r = retry(client, failed["run_id"], key="retry-1")
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    done = wait_done(client, run_id)
    assert done["status"] == "paid_mock" and done["retry_of"] == failed["run_id"]
    (stored,) = rows(settings, "SELECT trigger, version_id FROM runs WHERE run_id = ?", run_id)
    assert stored["trigger"] == "correction"
    assert counts(settings)["invoice_versions"] == 2  # no re-extraction
    assert counts(settings)["payments"] == 1
    again = retry(client, failed["run_id"], key="retry-1")
    assert again.json()["run_id"] == run_id and again.json()["idempotent_replay"] is True
    detail = client.get(f"/api/invoices/{invoice_id}").json()
    assert detail["current_version"] == 2 and detail["outcome"] == "paid_mock"
    assert SENTINEL not in r.text + str(done) + str(detail)


def test_failed_correction_run_cannot_run_offline(client, settings, live):
    _, failed = failed_correction(client, settings, live)
    before = counts(settings)
    r = retry(client, failed["run_id"], action="run_offline")
    assert r.status_code == 409 and r.json()["code"] == "not_recoverable"
    assert counts(settings) == before


def test_retry_of_a_correction_no_longer_current_is_409_not_current(client, settings, live):
    invoice_id, failed = failed_correction(client, settings, live)
    conn = storage.connect(settings.db_path)  # a later version became current
    try:
        conn.execute("UPDATE invoices SET current_version = 3 WHERE invoice_id = ?", (invoice_id,))
        conn.commit()
    finally:
        conn.close()
    before = counts(settings)
    r = retry(client, failed["run_id"])
    assert r.status_code == 409
    assert r.json()["code"] == "not_current"
    assert r.json()["message"] == api._RETRY_MESSAGES["not_current"]
    assert counts(settings) == before


# ------------------------------------------------------------------ approve / decline

THRESHOLD = Path(__file__).resolve().parent / "fixtures" / "threshold"


def decide(client, invoice_id, action, version=1, key="d-1", reason="Checked against PO"):
    headers = {"Idempotency-Key": key} if key else {}
    payload = {"expected_version": version, "reason": reason, "reviewer": "Ana"}
    return client.post(f"/api/invoices/{invoice_id}/{action}", json=payload, headers=headers)


def waiting(settings) -> str:
    r1 = process(THRESHOLD / "valid_10000_01.json", settings.db_path)
    assert r1.status == "awaiting_human_approval", r1
    return r1.invoice_id


def test_approve_returns_the_run_at_once_and_pays_once(client, settings):
    invoice_id = waiting(settings)
    r = decide(client, invoice_id, "approve")
    assert r.json()["idempotent_replay"] is False
    result = finished(client, r)
    assert result["status"] == "paid_mock" and result["receipt"]["amount"] == "10000.01"
    assert result["decision"]["reasons"] == ["R4_human_approved"]
    assert result["decision"]["human_review"]["reviewer"] == "Ana"
    (run,) = rows(settings, "SELECT trigger FROM runs WHERE run_id = ?", result["run_id"])
    assert run["trigger"] == "human_review"
    assert client.get(f"/api/runs/{result['run_id']}").json()["trigger"] == "human_review"
    detail = client.get(f"/api/invoices/{invoice_id}").json()
    assert detail["outcome"] == "paid_mock" and len(detail["human_reviews"]) == 1
    assert counts(settings)["payments"] == 1


def test_repeated_approve_key_replays_the_same_run_and_receipt(client, settings):
    invoice_id = waiting(settings)
    first = finished(client, decide(client, invoice_id, "approve", key="same"))
    after = counts(settings)
    again = decide(client, invoice_id, "approve", key="same")
    assert again.status_code == 202
    assert again.json() == {
        "run_id": first["run_id"],
        "status": "paid_mock",
        "mode": "offline",
        "idempotent_replay": True,
    }
    assert counts(settings) == after and after["payments"] == 1


def test_double_approve_with_a_new_key_returns_the_paying_run(client, settings):
    invoice_id = waiting(settings)
    first = finished(client, decide(client, invoice_id, "approve", key="one"))
    after = counts(settings)
    again = decide(client, invoice_id, "approve", key="two")  # Decision 20: no new run
    assert again.status_code == 200, again.text
    assert again.json()["run_id"] == first["run_id"] and again.json()["idempotent_replay"]
    replayed = client.get(f"/api/runs/{again.json()['run_id']}").json()["result"]
    assert replayed["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    assert counts(settings) == after and after["payments"] == 1


def test_approve_with_a_stale_version_is_409_and_pays_nothing(client, settings):
    invoice_id = waiting(settings)
    err = refused_decision(client, settings, invoice_id, "approve", 409, "stale_version", 2)
    assert err["details"]["current"]["current_version"] == 1
    assert err["details"]["invoice"] == client.get(f"/api/invoices/{invoice_id}").json()
    assert counts(settings)["payments"] == 0


def test_approve_on_a_needs_review_eur_invoice_is_409_action_not_allowed(client, settings):
    eur = process(INVOICES / "invoice_1014.xml", settings.db_path)
    assert eur.status == "needs_review"
    err = refused_decision(client, settings, eur.invoice_id, "approve", 409, "action_not_allowed")
    assert "approve" not in err["details"]["current"]["allowed"]
    assert err["details"]["invoice"]["outcome"] == "needs_review"


def test_decline_rejects_then_approve_is_refused(client, settings):
    invoice_id = waiting(settings)
    result = finished(client, decide(client, invoice_id, "decline", reason="Not on contract"))
    assert result["status"] == "rejected"
    assert result["decision"]["reasons"] == ["R3_human_declined"]
    err = refused_decision(client, settings, invoice_id, "approve", 409, "action_not_allowed")
    assert err["details"]["current"]["status"] == "rejected"
    assert counts(settings)["payments"] == 0


def test_decline_of_a_paid_invoice_is_409_already_paid(client, settings):
    paid = process(INVOICES / "invoice_1001.txt", settings.db_path)
    err = refused_decision(client, settings, paid.invoice_id, "decline", 409, "already_paid")
    assert err["details"]["invoice"]["outcome"] == "paid_mock"


def test_decision_on_an_unknown_invoice_is_404(client, settings):
    refused_decision(client, settings, "inv-nope", "approve", 404, "unknown_invoice")


@pytest.mark.parametrize("missing", ["reason", "reviewer", "expected_version"])
def test_decision_body_is_validated(client, settings, missing):
    invoice_id = waiting(settings)
    payload = {"expected_version": 1, "reason": "ok", "reviewer": "Ana"}
    del payload[missing]
    before = counts(settings)
    r = client.post(
        f"/api/invoices/{invoice_id}/approve", json=payload, headers={"Idempotency-Key": "k"}
    )
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert counts(settings) == before


def test_decision_requires_an_idempotency_key(client, settings):
    invoice_id = waiting(settings)
    r = decide(client, invoice_id, "approve", key=None)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert counts(settings)["payments"] == 0


def refused_decision(client, settings, invoice_id, action, status, code, version=1) -> dict:
    before = counts(settings)
    r = decide(client, invoice_id, action, version=version, key=f"{action}-{code}")
    assert r.status_code == status, r.text
    assert r.json()["code"] == code
    assert counts(settings) == before
    return r.json()


def test_interrupted_approve_is_retried_without_a_file_and_never_offline(
    client, settings, monkeypatch
):
    from invoice_processing import review, service

    invoice_id = waiting(settings)
    with monkeypatch.context() as m:  # commit the approval, then "crash" before the graph
        m.setattr(service, "run_existing_version", lambda run_id, **kw: run_id)
        run_id = review.approve(invoice_id, 1, "Ana", "Checked", db_path=settings.db_path)
    r = retry(client, run_id, action="run_offline")
    assert r.status_code == 409 and r.json()["code"] == "not_recoverable"  # sweep marks it
    r = retry(client, run_id)
    assert r.status_code == 202, r.text
    done = wait_done(client, r.json()["run_id"])
    assert done["status"] == "paid_mock" and done["trigger"] == "human_review"
    assert done["retry_of"] == run_id
    assert counts(settings)["payments"] == 1


# ------------------------------------------------------------------ review queue


def test_review_queue_groups_with_allowed_actions(client, settings):
    mistake = process(REVIEW / "extraction_mistake.txt", settings.db_path)
    high = waiting(settings)
    eur = process(INVOICES / "invoice_1014.xml", settings.db_path)
    process(INVOICES / "invoice_1001.txt", settings.db_path)  # paid: not queued
    groups = client.get("/api/review-queue").json()["groups"]
    ids = {g: [i["invoice_id"] for i in items] for g, items in groups.items()}
    assert ids == {
        "correctable_extraction": [mistake.invoice_id],
        "awaiting_human_approval": [high],
        "unresolved_blocker": [eur.invoice_id],
    }
    (item,) = groups["awaiting_human_approval"]
    assert item["total"] == "10000.01" and item["current_version"] == 1
    assert set(item["actions"]["allowed"]) == {"approve", "decline", "correct"}
    assert item["actions"] == client.get(f"/api/invoices/{high}").json()["review_actions"]
    finished(client, decide(client, high, "approve"))
    after = client.get("/api/review-queue").json()["groups"]
    assert after["awaiting_human_approval"] == []


def test_empty_review_queue(client):
    groups = client.get("/api/review-queue").json()["groups"]
    assert groups == {
        "correctable_extraction": [],
        "awaiting_human_approval": [],
        "unresolved_blocker": [],
    }


# ------------------------------------------------------------------ corrected submission

CORRECTED_1013 = REVIEW / "inv_1013_corrected.json"


def submit_corrected(client, invoice_id, path=CORRECTED_1013, key="cs-1", **fields):
    data = {"expected_version": "1", "reason": "Vendor reissued", "reviewer": "Ana", **fields}
    data = {k: v for k, v in data.items() if v is not None}
    files = {"file": (path.name, path.read_bytes(), "application/octet-stream")}
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(
        f"/api/invoices/{invoice_id}/corrected-submission", data=data, files=files, headers=headers
    )


def rejected_1013(settings) -> str:
    r1 = process(INVOICES / "invoice_1013.json", settings.db_path)
    assert r1.status == "rejected"
    return r1.invoice_id


def test_corrected_submission_supersedes_and_returns_the_run(client, settings):
    invoice_id = rejected_1013(settings)
    r = submit_corrected(client, invoice_id)
    result = finished(client, r)
    assert result["invoice_id"] == invoice_id and result["version"] == 2
    assert result["status"] == "awaiting_human_approval"
    run = client.get(f"/api/runs/{result['run_id']}").json()
    assert run["trigger"] == "corrected_submission"
    detail = client.get(f"/api/invoices/{invoice_id}").json()
    assert detail["current_version"] == 2 and detail["outcome"] == "awaiting_human_approval"
    assert len(detail["versions"]) == 2
    # The uploaded file is stored like any upload, so the run can be retried from it.
    assert any(settings.uploads_dir.rglob(CORRECTED_1013.name))


def test_corrected_submission_replays_a_repeated_key(client, settings):
    invoice_id = rejected_1013(settings)
    first = finished(client, submit_corrected(client, invoice_id, key="same"))
    after = counts(settings)
    again = submit_corrected(client, invoice_id, key="same")
    assert again.status_code == 202
    assert again.json()["run_id"] == first["run_id"] and again.json()["idempotent_replay"]
    assert counts(settings) == after
    other = submit_corrected(client, invoice_id, key="same", reason="Different")
    assert other.status_code == 422 and other.json()["code"] == "idempotency_key_reused"


def test_corrected_submission_with_another_identity_fails_its_run(client, settings):
    invoice_id = rejected_1013(settings)
    result = finished(client, submit_corrected(client, invoice_id, REVIEW / "source_error.json"))
    assert result["status"] == "failed" and result["errors"] == ["corrected_identity_mismatch"]
    assert "run offline as a separate simulation" not in result["next_actions"]
    detail = client.get(f"/api/invoices/{invoice_id}").json()
    assert detail["current_version"] == 1 and detail["outcome"] == "rejected"


def test_corrected_submission_with_a_stale_version_is_409(client, settings):
    invoice_id = rejected_1013(settings)
    before = counts(settings)
    r = submit_corrected(client, invoice_id, expected_version="2")
    assert r.status_code == 409 and r.json()["code"] == "stale_version"
    assert r.json()["details"]["current"]["current_version"] == 1
    assert r.json()["details"]["invoice"]["invoice_id"] == invoice_id
    assert counts(settings) == before


@pytest.mark.parametrize(
    "case,status,code",
    [
        ("paid", 409, "already_paid"),
        ("waiting", 409, "action_not_allowed"),
        ("unknown", 404, "unknown_invoice"),
    ],
)
def test_corrected_submission_refusals(client, settings, case, status, code):
    if case == "paid":
        invoice_id = process(INVOICES / "invoice_1001.txt", settings.db_path).invoice_id
    elif case == "waiting":
        invoice_id = waiting(settings)
    else:
        invoice_id = "inv-nope"
    before = counts(settings)
    r = submit_corrected(client, invoice_id)
    assert r.status_code == status, r.text
    assert r.json()["code"] == code
    assert counts(settings) == before


@pytest.mark.parametrize("missing", ["reason", "reviewer", "expected_version"])
def test_corrected_submission_fields_are_required(client, settings, missing):
    invoice_id = rejected_1013(settings)
    before = counts(settings)
    r = submit_corrected(client, invoice_id, **{missing: None})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert counts(settings) == before


def test_corrected_submission_uses_the_upload_checks(client, settings, tmp_path):
    invoice_id = rejected_1013(settings)
    before = counts(settings)
    bad = tmp_path / "corrected.exe"
    bad.write_bytes(b"MZ")
    r = submit_corrected(client, invoice_id, bad)
    assert r.status_code == 422 and r.json()["code"] == "unsupported_format", r.text
    settings.limits = type(settings.limits)(**{**settings.limits.__dict__, "max_bytes": 10})
    big = submit_corrected(client, invoice_id, key="cs-big")
    assert big.status_code == 413 and big.json()["code"] == "file_too_large"
    fields = {"expected_version": "1", "reason": "r", "reviewer": "Ana"}
    # A multipart form without a file part is 422; a url-encoded form is not multipart (415).
    r = client.post(
        f"/api/invoices/{invoice_id}/corrected-submission",
        files={k: (None, v) for k, v in fields.items()},
        headers={"Idempotency-Key": "cs-nofile"},
    )
    assert r.status_code == 422, r.text
    r = client.post(
        f"/api/invoices/{invoice_id}/corrected-submission",
        data=fields,
        headers={"Idempotency-Key": "cs-urlencoded"},
    )
    assert r.status_code == 415 and r.json()["code"] == "unsupported_media_type"
    assert counts(settings) == before


def test_corrected_submission_requires_an_idempotency_key(client, settings):
    invoice_id = rejected_1013(settings)
    r = submit_corrected(client, invoice_id, key=None)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


# ------------------------------------------------------------------ next_actions of review runs


def test_failed_review_run_results_never_offer_the_offline_run(client, settings, live):
    _, failed = failed_correction(client, settings, live)
    assert failed["next_actions"] == ["retry"]
    detail = client.get(f"/api/invoices/{failed['invoice_id']}").json()
    assert detail["latest_result"]["next_actions"] == ["retry"]
