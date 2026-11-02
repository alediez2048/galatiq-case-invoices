"""Local web security of the HTTP API (Phase 5 review fix wave).

Threat model: an unauthenticated API on loopback, and a browser on the same machine that may
also have a hostile page open. Checks: Origin on state-changing requests, Host (DNS
rebinding), Content-Type, required Idempotency-Key (forces a CORS preflight), the original-file
route's headers, error envelopes, body limits and /api/runs key fingerprints.

TestClient only; no network. TestClient sends ``Host: testserver``, which the default settings
refuse, so the fixture adds it explicitly (tests only)."""

import io
import json
import threading
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_processing import api, uploads
from tests.test_api import EVAL, SAMPLES, TEST_HOSTS, wait_done

EVIL_XML = Path("tests/fixtures/security/evil.xml")
FOREIGN = "https://evil.example"
MiB = 1024 * 1024


@pytest.fixture
def settings(tmp_path) -> api.ApiSettings:
    s = api.ApiSettings(
        db_path=tmp_path / "api.db",
        uploads_dir=tmp_path / "uploads",
        samples_dir=SAMPLES,
        frontend_dist=tmp_path / "no-dist",
        evaluation_date=EVAL,
    )
    s.allowed_hosts = TEST_HOSTS
    return s


@pytest.fixture
def client(settings):
    with TestClient(api.create_app(settings)) as c:
        yield c


def key() -> str:
    return str(uuid.uuid4())


def runs(client) -> int:
    return client.get("/api/overview").json()["runs"]


def run_body(sample="invoice_1001.txt", mode="offline", **extra) -> str:
    return json.dumps({"sample": sample, "mode": mode, **extra})


def post_json(client, path, body: str, k: str | None = None, **headers):
    h = {"Content-Type": "application/json", **headers}
    if k:
        h["Idempotency-Key"] = k
    return client.post(path, content=body, headers=h)


def upload(client, name, data: bytes, k: str | None = None, mode="offline", headers=None, **form):
    h = dict(headers or {})
    if k:
        h["Idempotency-Key"] = k
    return client.post(
        "/api/runs",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
        data={"mode": mode, **form},
        headers=h,
    )


def stored_files(settings) -> list[Path]:
    return [p for p in settings.uploads_dir.rglob("*") if p.is_file()]


# ------------------------------------------------------------------ Critical 1: Origin


def test_reviewer_repro_text_plain_with_foreign_origin_is_refused_and_creates_no_run(client):
    # curl -X POST /api/runs -H 'Origin: https://evil.example' -H 'Content-Type: text/plain'
    #      --data '{"sample":"invoice_1001.txt","mode":"offline"}'   (was 202, then paid)
    r = client.post(
        "/api/runs",
        content=run_body(),
        headers={"Origin": FOREIGN, "Content-Type": "text/plain"},
    )
    assert r.status_code == 403
    assert r.json() == {
        "code": "forbidden_origin",
        "message": r.json()["message"],
        "details": None,
    }
    assert runs(client) == 0


def test_foreign_origin_is_refused_even_with_json_and_a_key(client):
    r = post_json(client, "/api/runs", run_body(), key(), Origin=FOREIGN)
    assert r.status_code == 403 and r.json()["code"] == "forbidden_origin"
    assert runs(client) == 0


def test_foreign_origin_multipart_upload_is_refused_and_nothing_is_stored(client, settings):
    data = (SAMPLES / "invoice_1001.txt").read_bytes()
    r = upload(client, "x.txt", data, key(), headers={"Origin": FOREIGN})
    assert r.status_code == 403 and r.json()["code"] == "forbidden_origin"
    assert runs(client) == 0
    assert stored_files(settings) == []


def test_foreign_origin_retry_without_body_is_refused(client):
    r = client.post("/api/runs/run-nope/retry", headers={"Origin": FOREIGN})
    assert r.status_code == 403 and r.json()["code"] == "forbidden_origin"


@pytest.mark.parametrize(
    "path", ["/api/invoices/inv-x/approve", "/api/invoices/inv-x/decline", "/api/runs/r/retry"]
)
def test_foreign_origin_is_refused_on_every_post(client, path):
    body = json.dumps({"expected_version": 1, "reason": "r", "reviewer": "Ana"})
    r = post_json(client, path, body, key(), Origin=FOREIGN)
    assert r.status_code == 403 and r.json()["code"] == "forbidden_origin"


@pytest.mark.parametrize("origin", ["null", "http://127.0.0.1:5174", "http://localhost.evil"])
def test_opaque_or_lookalike_origins_are_refused(client, origin):
    r = post_json(client, "/api/runs", run_body(), key(), Origin=origin)
    assert r.status_code == 403
    assert runs(client) == 0


@pytest.mark.parametrize(
    "origin", ["http://localhost:5173", "http://127.0.0.1:5173", "http://testserver"]
)
def test_vite_dev_origin_and_same_origin_are_accepted(client, origin):
    r = post_json(client, "/api/runs", run_body(), key(), Origin=origin)
    assert r.status_code == 202, r.text
    wait_done(client, r.json()["run_id"])


def test_reads_are_not_origin_checked(client):
    # A foreign page cannot read the response (CORS); a GET changes nothing.
    assert client.get("/api/health", headers={"Origin": FOREIGN}).status_code == 200


# ------------------------------------------------------------------ Critical 1: Content-Type


def test_text_plain_run_body_is_415_without_an_origin(client):
    r = client.post(
        "/api/runs",
        content=run_body(),
        headers={"Content-Type": "text/plain", "Idempotency-Key": key()},
    )
    assert r.status_code == 415 and r.json()["code"] == "unsupported_media_type"
    assert runs(client) == 0


def test_run_without_content_type_is_415(client):
    r = client.post("/api/runs", content=run_body(), headers={"Idempotency-Key": key()})
    assert r.status_code == 415
    assert runs(client) == 0


def test_json_with_charset_is_accepted(client):
    r = post_json(
        client,
        "/api/runs",
        run_body(),
        key(),
        **{"Content-Type": "application/json; charset=utf-8"},
    )
    assert r.status_code == 202, r.text
    wait_done(client, r.json()["run_id"])


@pytest.mark.parametrize("path", ["/api/invoices/inv-x/approve", "/api/invoices/inv-x/decline"])
def test_review_json_routes_refuse_text_plain_and_multipart(client, path):
    body = json.dumps({"expected_version": 1, "reason": "r", "reviewer": "Ana"})
    r = client.post(
        path, content=body, headers={"Content-Type": "text/plain", "Idempotency-Key": key()}
    )
    assert r.status_code == 415 and r.json()["code"] == "unsupported_media_type"
    r = client.post(
        path,
        data={"expected_version": "1", "reason": "r", "reviewer": "Ana"},
        files={"file": ("a.txt", b"x", "text/plain")},
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 415


def test_retry_refuses_text_plain_but_allows_an_empty_body(client):
    r = client.post(
        "/api/runs/run-nope/retry",
        content=b'{"action":"retry"}',
        headers={"Content-Type": "text/plain", "Idempotency-Key": key()},
    )
    assert r.status_code == 415
    r = client.post("/api/runs/run-nope/retry", headers={"Idempotency-Key": key()})
    assert r.status_code == 404 and r.json()["code"] == "unknown_run"


def test_corrected_submission_requires_multipart(client):
    body = json.dumps({"expected_version": 1, "reason": "r", "reviewer": "Ana"})
    r = post_json(client, "/api/invoices/inv-x/corrected-submission", body, key())
    assert r.status_code == 415 and r.json()["code"] == "unsupported_media_type"


# ------------------------------------------------------------------ Critical 1: Idempotency-Key


def test_runs_require_an_idempotency_key(client, settings):
    r = post_json(client, "/api/runs", run_body())
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert any("idempotency-key" in d["loc"] for d in r.json()["details"])
    data = (SAMPLES / "invoice_1001.txt").read_bytes()
    r = upload(client, "x.txt", data)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert runs(client) == 0
    assert stored_files(settings) == []


def test_retry_requires_an_idempotency_key(client):
    r = post_json(client, "/api/runs/run-nope/retry", json.dumps({"action": "retry"}))
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


def test_openapi_marks_the_key_required_on_runs_and_retry(client):
    spec = client.get("/openapi.json").json()
    for path in ("/api/runs", "/api/runs/{run_id}/retry"):
        params = spec["paths"][path]["post"]["parameters"]
        header = next(p for p in params if p["name"] == "idempotency-key")
        assert header["required"] is True, path


# ------------------------------------------------------------------ Critical 1: Host


def test_default_settings_trust_only_loopback_hosts():
    assert api.ApiSettings().allowed_hosts == ("127.0.0.1", "localhost", "::1")


def test_reviewer_repro_foreign_host_is_400(tmp_path):
    settings = api.ApiSettings(
        db_path=tmp_path / "api.db", uploads_dir=tmp_path / "u", frontend_dist=tmp_path / "nd"
    )
    with TestClient(api.create_app(settings), base_url="http://127.0.0.1:8000") as c:
        assert c.get("/api/health").status_code == 200
        r = c.get("/api/health", headers={"Host": "attacker.example"})
        assert r.status_code == 400
        r = c.post(
            "/api/runs",
            content=run_body(),
            headers={
                "Host": "attacker.example:8000",
                "Content-Type": "application/json",
                "Idempotency-Key": key(),
            },
        )
        assert r.status_code == 400
        assert c.get("/api/overview").json()["runs"] == 0


@pytest.mark.parametrize(
    "base", ["http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000"]
)
def test_loopback_hosts_are_served_by_default(tmp_path, base):
    settings = api.ApiSettings(
        db_path=tmp_path / "api.db", uploads_dir=tmp_path / "u", frontend_dist=tmp_path / "nd"
    )
    with TestClient(api.create_app(settings), base_url=base) as c:
        assert c.get("/api/health").status_code == 200


def test_testclient_host_is_refused_by_default(tmp_path):
    settings = api.ApiSettings(
        db_path=tmp_path / "api.db", uploads_dir=tmp_path / "u", frontend_dist=tmp_path / "nd"
    )
    with TestClient(api.create_app(settings)) as c:
        assert c.get("/api/health").status_code == 400


# ------------------------------------------------------------------ Important 2: original file


def _evil_source(client) -> str:
    r = upload(client, "evil.xml", EVIL_XML.read_bytes(), key())
    assert r.status_code == 202, r.text
    return wait_done(client, r.json()["run_id"])["source"]["source_id"]


def test_reviewer_repro_evil_xml_is_served_as_inert_text_attachment(client):
    src = _evil_source(client)
    r = client.get(f"/api/sources/{src}/original")
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["content-disposition"].startswith("attachment")
    assert 'filename="evil.xml"' in r.headers["content-disposition"]
    assert r.content == EVIL_XML.read_bytes()


def test_non_pdf_sources_have_no_original_url(client):
    src = _evil_source(client)
    assert client.get(f"/api/sources/{src}/content").json()["original_url"] is None


def test_pdf_original_stays_inline_with_the_sandbox_policy(client):
    r = post_json(client, "/api/runs", run_body("invoice_1011.pdf"), key())
    src = wait_done(client, r.json()["run_id"])["source"]["source_id"]
    body = client.get(f"/api/sources/{src}/content").json()
    assert body["original_url"] == f"/api/sources/{src}/original"
    o = client.get(body["original_url"])
    assert o.headers["content-type"] == "application/pdf"
    assert o.headers["content-disposition"] == "inline"
    assert o.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert o.headers["x-content-type-options"] == "nosniff"


# ------------------------------------------------------------------ Important 3: envelopes


def test_reviewer_repro_malformed_multipart_is_a_422_envelope(client, settings):
    r = client.post(
        "/api/runs",
        content=b"garbage",
        headers={
            "Content-Type": "multipart/form-data; boundary=zz",
            "Idempotency-Key": key(),
        },
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error" and set(r.json()) == {
        "code",
        "message",
        "details",
    }
    assert runs(client) == 0
    assert not [p for p in (settings.uploads_dir / ".tmp").glob("*")]


def test_unexpected_exception_is_an_internal_error_envelope_without_internals(settings):
    app = api.create_app(settings)

    @app.get("/api/_crash")
    def crash():
        raise RuntimeError("secret at /Users/someone/private/path.py")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/_crash")
    assert r.status_code == 500
    body = r.json()
    assert body["code"] == "internal_error" and body["details"] is None and body["message"]
    assert "secret" not in r.text and "Traceback" not in r.text and "/Users" not in r.text


# ------------------------------------------------------------------ Important 4: run keys


def test_same_run_key_with_another_sample_is_refused(client):
    k = key()
    first = post_json(client, "/api/runs", run_body("invoice_1002.txt"), k)
    assert first.status_code == 202
    wait_done(client, first.json()["run_id"])
    again = post_json(client, "/api/runs", run_body("invoice_1002.txt"), k)
    assert again.status_code == 202 and again.json()["idempotent_replay"] is True
    for body in (
        run_body("invoice_1004.json"),
        run_body("invoice_1002.txt", evaluation_date="2026-01-10"),
        run_body("invoice_1002.txt", mode="live"),
    ):
        r = post_json(client, "/api/runs", body, k)
        assert r.status_code == 422 and r.json()["code"] == "idempotency_key_reused", body
    r = upload(client, "invoice_1002.txt", (SAMPLES / "invoice_1002.txt").read_bytes(), k)
    assert r.status_code == 422 and r.json()["code"] == "idempotency_key_reused"
    assert runs(client) == 1


def test_same_upload_key_replays_only_the_same_bytes(client):
    k = key()
    data = (SAMPLES / "invoice_1001.txt").read_bytes()
    first = upload(client, "a.txt", data, k)
    wait_done(client, first.json()["run_id"])
    same = upload(client, "a.txt", data, k)
    assert same.json() == {**first.json(), "idempotent_replay": True, "status": "paid_mock"}
    other = upload(client, "a.txt", (SAMPLES / "invoice_1002.txt").read_bytes(), k)
    assert other.status_code == 422 and other.json()["code"] == "idempotency_key_reused"
    assert runs(client) == 1


# ------------------------------------------------------------------ Minor 1: lock wait


def _in_thread(fn):
    out: dict = {}

    def target():
        t0 = time.monotonic()
        out["response"] = fn()
        out["elapsed"] = time.monotonic() - t0

    t = threading.Thread(target=target)
    t.start()
    return t, out


def test_replay_is_answered_without_waiting_for_the_lock(client):
    k = key()
    first = post_json(client, "/api/runs", run_body(), k)
    wait_done(client, first.json()["run_id"])
    api._idempotency_lock.acquire()
    try:
        t, out = _in_thread(lambda: post_json(client, "/api/runs", run_body(), k))
        t.join(timeout=3)
        replied = not t.is_alive()
    finally:
        api._idempotency_lock.release()
        t.join()
    assert replied, "the replay waited for the idempotency lock"
    assert out["response"].json()["idempotent_replay"] is True


def test_review_action_replay_is_answered_without_waiting_for_the_lock(client, settings):
    from tests.test_api_review import decide, waiting

    invoice_id = waiting(settings)
    first = decide(client, invoice_id, "approve", key="ap-1")
    wait_done(client, first.json()["run_id"])
    api._idempotency_lock.acquire()
    try:
        t, out = _in_thread(lambda: decide(client, invoice_id, "approve", key="ap-1"))
        t.join(timeout=3)
        replied = not t.is_alive()
    finally:
        api._idempotency_lock.release()
        t.join()
    assert replied, "the replay waited for the idempotency lock"
    assert out["response"].json()["run_id"] == first.json()["run_id"]
    assert out["response"].json()["idempotent_replay"] is True


def test_a_busy_review_action_waits_one_deadline_then_gets_503(client, settings):
    from tests.test_api_review import decide, waiting

    invoice_id = waiting(settings)
    settings.run_start_timeout_s = 0.3
    api._idempotency_lock.acquire()
    try:
        t, out = _in_thread(lambda: decide(client, invoice_id, "approve", key="ap-2"))
        t.join(timeout=2)
    finally:
        api._idempotency_lock.release()
        t.join()
    assert out["response"].status_code == 503 and out["elapsed"] < 1.5


def test_a_busy_request_waits_one_deadline_then_gets_503(client, settings):
    settings.run_start_timeout_s = 0.3
    api._idempotency_lock.acquire()
    try:
        t, out = _in_thread(lambda: post_json(client, "/api/runs", run_body(), key()))
        t.join(timeout=2)
    finally:
        api._idempotency_lock.release()
        t.join()
    r = out["response"]
    assert r.status_code == 503 and r.json()["code"] == "busy"
    assert out["elapsed"] < 1.5
    assert runs(client) == 0


# ------------------------------------------------------------------ Minor 2: body limits


def test_oversized_json_body_is_413_and_starts_nothing(client):
    big = run_body(padding="x" * (api.MAX_JSON_BODY_BYTES + 1))
    r = post_json(client, "/api/runs", big, key())
    assert r.status_code == 413 and r.json()["code"] == "body_too_large"
    body = json.dumps(
        {"expected_version": 1, "reason": "x" * (api.MAX_JSON_BODY_BYTES + 1), "reviewer": "A"}
    )
    r = post_json(client, "/api/invoices/inv-x/approve", body, key())
    assert r.status_code == 413 and r.json()["code"] == "body_too_large"
    assert runs(client) == 0


def test_too_many_form_fields_is_422(client):
    fields = {f"f{i}": "x" for i in range(uploads.MAX_PARTS + 1)}
    r = upload(client, "a.txt", (SAMPLES / "invoice_1001.txt").read_bytes(), key(), **fields)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert runs(client) == 0


def test_total_streamed_bytes_are_capped_including_ignored_file_parts(settings):
    """A second file part is not stored, but its bytes still count (no Content-Length)."""
    import asyncio

    from starlette.requests import Request

    boundary = "XB"
    small = 1024
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\n'
        "hello\r\n"
        f'--{boundary}\r\nContent-Disposition: form-data; name="f2"; filename="b.txt"\r\n\r\n'
    ).encode() + b"B" * (uploads.ENVELOPE_ALLOWANCE + 2 * small)
    chunk = 64 * 1024
    pieces = [body[i : i + chunk] for i in range(0, len(body), chunk)]
    sent = {"n": 0}

    async def receive():
        i = sent["n"]
        sent["n"] += 1
        if i < len(pieces):
            return {"type": "http.request", "body": pieces[i], "more_body": True}
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
    }

    async def run():
        with pytest.raises(uploads.UploadTooLarge):
            await uploads.read_multipart(
                Request(scope, receive), settings.uploads_dir / ".t", small
            )

    asyncio.run(run())
    assert sent["n"] <= len(pieces)
    assert not list((settings.uploads_dir / ".t").glob("*"))


# ------------------------------------------------------------------ Minor 3: readiness


def test_readiness_reports_only_the_database_file_name(client, settings):
    body = client.get("/api/settings/readiness").json()
    assert body["database_path"] == "api.db"
    assert str(settings.db_path.parent) not in json.dumps(body)
