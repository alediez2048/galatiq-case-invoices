"""HTTP API (P5-01, P5-02, P5-03): TestClient against a fresh temporary database per test."""

import ast
import io
import time
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_processing import api, ledger, storage
from invoice_processing.codes import ExecutionMode
from invoice_processing.service import process_invoice

SAMPLES = Path("data/invoices")
EVAL = date(2026, 1, 31)
MiB = 1024 * 1024


@pytest.fixture
def settings(tmp_path) -> api.ApiSettings:
    return api.ApiSettings(
        db_path=tmp_path / "api.db",
        uploads_dir=tmp_path / "uploads",
        samples_dir=SAMPLES,
        frontend_dist=tmp_path / "no-dist",
        evaluation_date=EVAL,
    )


@pytest.fixture
def client(settings):
    with TestClient(api.create_app(settings)) as c:
        yield c


def wait_done(client, run_id, timeout=30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        # The status turns terminal just before the service's closing event is written.
        if body["terminal"] and any(e["stage"] == "service" for e in body["events"]):
            return body
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish: {body}")


def submit(client, sample, mode="offline", key=None, **extra):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/api/runs", json={"sample": sample, "mode": mode, **extra}, headers=headers)


def process(client, *names) -> list[dict]:
    done = []
    for name in names:
        r = submit(client, name)
        assert r.status_code == 202, r.text
        done.append(wait_done(client, r.json()["run_id"]))
    return done


# ------------------------------------------------------------------ P5-01


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_readiness_without_live_key_exposes_only_availability(client, settings, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    body = client.get("/api/settings/readiness").json()
    assert body["modes"]["offline"] == {"available": True, "reason": None}
    assert body["modes"]["live"]["available"] is False
    assert body["live_settings_present"] is False
    assert body["inventory_seeded"] is True
    assert body["database_path"] == str(settings.db_path)
    assert set(body) == {
        "modes",
        "live_settings_present",
        "inventory_seeded",
        "database_path",
        "schema_version",
        "live_model",
    }


def test_startup_seeds_idempotently_without_resetting(settings):
    api.create_app(settings)
    conn = storage.connect(settings.db_path)
    conn.execute("UPDATE inventory SET stock = 3 WHERE item = 'WidgetA'")
    conn.close()
    api.create_app(settings)
    conn = storage.connect(settings.db_path)
    assert storage.get_stock(conn, ["WidgetA"]) == {"WidgetA": 3}
    conn.close()


def test_error_body_shape_and_mapping(settings):
    app = api.create_app(settings)

    @app.get("/api/_boom/{code}")
    def boom(code: str):
        raise api.ApiError(code, "boom", {"x": 1})

    with TestClient(app) as c:
        for code, status in [
            ("stale_version", 409),
            ("action_not_allowed", 409),
            ("validation_error", 422),
            ("not_found", 404),
            ("file_too_large", 413),
        ]:
            r = c.get(f"/api/_boom/{code}")
            assert r.status_code == status
            assert r.json() == {"code": code, "message": "boom", "details": {"x": 1}}
        r = c.get("/api/runs/run-nope")
        assert r.status_code == 404
        assert (
            set(r.json()) == {"code", "message", "details"} and r.json()["code"] == "run_not_found"
        )
        r = c.get("/api/invoices", params={"page": 0})
        assert r.status_code == 422 and r.json()["code"] == "validation_error"
        assert c.get("/api/nothing-here").json()["code"] == "not_found"


def test_bind_host_refuses_public_without_flag():
    api.check_bind_host("127.0.0.1", False)
    api.check_bind_host("localhost", False)
    with pytest.raises(ValueError):
        api.check_bind_host("0.0.0.0", False)
    api.check_bind_host("0.0.0.0", True)
    assert api.main(["--host", "0.0.0.0"]) == 2


def test_cors_allows_only_the_vite_origin(client):
    ok = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_routes_do_not_import_policy_or_payment_logic():
    banned = {"policy", "payments", "validation", "agents", "workflow", "normalize", "parsers"}
    for name in ["api", "queries", "uploads", "samples", "idempotency"]:
        tree = ast.parse(Path(f"src/invoice_processing/{name}.py").read_text())
        for node in ast.walk(tree):
            mods: set[str] = set()
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[0] == "invoice_processing":
                    mods.add(parts[1] if len(parts) > 1 else "")
                    mods.update(a.name for a in node.names if len(parts) == 1)
            elif isinstance(node, ast.Import):
                mods.update(a.name.split(".")[1] for a in node.names if "." in a.name)
            assert not (mods & banned), f"{name}.py imports {mods & banned}"


def test_openapi_exports_and_models_hide_internal_reasoning(client):
    spec = client.get("/openapi.json").json()
    assert "/api/runs" in spec["paths"] and "/api/overview" in spec["paths"]
    forbidden = ("prompt", "reasoning", "secret", "api_key", "apikey", "token", "password")
    # A version label of the prompt template (Phase 3), not prompt text.
    allowed = {"prompt_version"}
    for name, schema in spec["components"]["schemas"].items():
        for prop in schema.get("properties", {}):
            if prop in allowed:
                continue
            assert not any(word in prop.lower() for word in forbidden), f"{name}.{prop}"


# ------------------------------------------------------------------ P5-02


def test_samples_listed_with_input_labels(client):
    body = client.get("/api/samples").json()
    names = {s["name"]: s for s in body}
    assert len(body) == 20
    assert names["invoice_1001.txt"]["label"] == "Clean invoice"
    assert names["invoice_1001.txt"]["invoice_number"] == "INV-1001"
    outcome_words = ("paid", "rejected", "approved", "fail", "success")
    assert not any(w in s["label"].lower() for s in body for w in outcome_words)


def test_post_run_returns_202_and_polls_to_result(client):
    r = submit(client, "invoice_1001.txt")
    assert r.status_code == 202
    accepted = r.json()
    assert accepted["mode"] == "offline" and accepted["idempotent_replay"] is False
    done = wait_done(client, accepted["run_id"])
    assert done["status"] == "paid_mock"
    assert done["result"]["receipt"]["amount"] == "5000.00"
    assert done["source"]["original_name"] == "invoice_1001.txt"


def test_polling_events_are_exactly_the_audit_events(client, settings):
    run_id = process(client, "invoice_1002.txt")[0]["run_id"]
    first = client.get(f"/api/runs/{run_id}").json()["events"]
    assert first == client.get(f"/api/runs/{run_id}").json()["events"]
    conn = storage.connect(settings.db_path)
    assert first == ledger.list_audit_events(conn, run_id)
    conn.close()
    assert [e["stage"] for e in first][0] == "intake" and first[-1]["event"] == "finished"


def test_same_idempotency_key_creates_one_run(client, settings):
    a = submit(client, "invoice_1001.txt", key="k-1").json()
    b = submit(client, "invoice_1001.txt", key="k-1").json()
    assert a["run_id"] == b["run_id"] and b["idempotent_replay"] is True
    wait_done(client, a["run_id"])
    assert client.get("/api/overview").json()["runs"] == 1
    c = submit(client, "invoice_1002.txt", key="k-2").json()
    assert c["run_id"] != a["run_id"]


def test_refresh_and_polling_never_start_processing(client):
    run_id = process(client, "invoice_1001.txt")[0]["run_id"]
    for _ in range(3):
        client.get(f"/api/runs/{run_id}")
        client.get("/api/overview")
        client.get("/api/samples")
    ov = client.get("/api/overview").json()
    assert ov["runs"] == 1 and ov["paid_totals"][0]["paid_count"] == 1


def test_second_submission_of_same_file_is_a_duplicate_run(client):
    first, second = process(client, "invoice_1001.txt", "invoice_1001.txt")
    assert first["status"] == "paid_mock" and second["status"] == "duplicate"
    assert second["result"]["prior_run_id"] == first["run_id"]


@pytest.mark.parametrize(
    "name",
    [
        "../data/invoices/invoice_1001.txt",
        "sub/invoice_1001.txt",
        "nope.txt",
        "",
        "..",
        "/etc/passwd",
    ],
)
def test_sample_name_must_be_a_listed_basename(client, name):
    r = submit(client, name)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert client.get("/api/overview").json()["runs"] == 0


def test_mode_is_required_and_validated(client):
    assert client.post("/api/runs", json={"sample": "invoice_1001.txt"}).status_code == 422
    assert submit(client, "invoice_1001.txt", mode="turbo").status_code == 422
    assert submit(client, "invoice_1001.txt", evaluation_date="31/01/2026").status_code == 422


def test_live_mode_refused_with_readiness_error_and_no_run(client, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    r = submit(client, "invoice_1001.txt", mode="live")
    assert r.status_code == 409
    assert r.json()["code"] == "provider_unavailable" and r.json()["message"]
    assert client.get("/api/overview").json()["runs"] == 0


def test_evaluation_date_is_honoured(client):
    # 1003 is past due on the default evaluation date; use a date long before to compare
    r = submit(client, "invoice_1001.txt", evaluation_date="2026-01-10")
    done = wait_done(client, r.json()["run_id"])
    assert done["result"]["evaluation_date"] == "2026-01-10"


def multipart(client, name, data: bytes, mode="offline", **kw):
    return client.post(
        "/api/runs",
        files={"file": (name, io.BytesIO(data), "text/plain")},
        data={"mode": mode},
        **kw,
    )


def test_upload_processes_and_is_stored_by_hash(client, settings):
    data = (SAMPLES / "invoice_1001.txt").read_bytes()
    r = multipart(client, "my invoice.txt", data)
    assert r.status_code == 202, r.text
    done = wait_done(client, r.json()["run_id"])
    assert done["status"] == "paid_mock"
    stored = [p for p in settings.uploads_dir.rglob("*") if p.is_file()]
    assert len(stored) == 1
    assert stored[0].parent.name == done["result"]["source_hash"]
    assert stored[0].name == "my_invoice.txt"


def test_traversal_filename_is_stored_safely(client, settings, tmp_path):
    data = (SAMPLES / "invoice_1001.txt").read_bytes()
    r = multipart(client, "../../x.txt", data)
    assert r.status_code == 202, r.text
    wait_done(client, r.json()["run_id"])
    stored = [p for p in settings.uploads_dir.rglob("*") if p.is_file()]
    assert [p.name for p in stored] == ["x.txt"]
    assert stored[0].resolve().is_relative_to(settings.uploads_dir.resolve())
    assert not (tmp_path / "x.txt").exists() and not (tmp_path.parent / "x.txt").exists()


def test_oversized_upload_rejected_with_413_and_nothing_kept(client, settings):
    r = multipart(client, "big.txt", b"A" * (11 * MiB))
    assert r.status_code == 413
    assert r.json()["code"] == "file_too_large" and "10 MiB" in r.json()["message"]
    assert not [p for p in settings.uploads_dir.rglob("*") if p.is_file()]
    assert client.get("/api/overview").json()["runs"] == 0


def test_streaming_cap_applies_without_content_length(settings):
    from invoice_processing import uploads

    boundary = "XBOUND"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\n'
        ).encode()
        + b"A" * (11 * MiB)
        + f"\r\n--{boundary}--\r\n".encode()
    )

    async def run():
        sent = {"n": 0}

        async def receive():
            if sent["n"] == 0:
                sent["n"] = 1
                return {"type": "http.request", "body": body[: MiB // 2], "more_body": True}
            if sent["n"] < 30:
                sent["n"] += 1
                start = (sent["n"] - 1) * MiB // 2
                return {
                    "type": "http.request",
                    "body": body[start : start + MiB // 2],
                    "more_body": sent["n"] < 30,
                }
            return {"type": "http.request", "body": b"", "more_body": False}

        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
        }
        req = Request(scope, receive)
        with pytest.raises(uploads.UploadTooLarge):
            await uploads.read_multipart(req, settings.uploads_dir / ".tmp", 10 * MiB)
        assert sent["n"] < 30  # stopped before consuming the whole body

    import asyncio

    asyncio.run(run())
    assert not [p for p in (settings.uploads_dir / ".tmp").glob("*")]


def test_unsupported_upload_is_422_and_leaves_no_file(client, settings):
    r = multipart(client, "notes.docx", b"hello")
    assert r.status_code == 422 and r.json()["code"] == "unsupported_format"
    assert not [p for p in settings.uploads_dir.rglob("*") if p.is_file()]


# ------------------------------------------------------------------ P5-03


def test_overview_after_four_samples(client):
    process(client, "invoice_1001.txt", "invoice_1004.json", "invoice_1002.txt", "invoice_1014.xml")
    ov = client.get("/api/overview").json()
    assert ov["unique_invoices"] == 4 and ov["documents"] == 4 and ov["runs"] == 4
    assert ov["outcomes"]["paid_mock"] == 2
    assert ov["outcomes"]["rejected"] == 1
    assert ov["outcomes"]["needs_review"] == 1
    totals = {t["currency"]: t for t in ov["paid_totals"]}
    assert totals["USD"]["amount"] == "6890.00" and totals["USD"]["paid_count"] == 2
    assert totals["EUR"]["amount"] == "0.00" and totals["EUR"]["paid_count"] == 0
    assert len(ov["recent_invoices"]) == 4


def test_txt_then_pdf_of_same_invoice_counts_once(client):
    process(client, "invoice_1011.txt", "invoice_1011.pdf")
    ov = client.get("/api/overview").json()
    assert (ov["documents"], ov["runs"], ov["unique_invoices"]) == (2, 2, 1)
    assert ov["outcomes"]["paid_mock"] == 1 and ov["duplicates"] == 1
    assert [t["amount"] for t in ov["paid_totals"]] == ["3000.00"]


def test_invoice_list_filters_search_and_pages(client):
    process(client, "invoice_1001.txt", "invoice_1002.txt", "invoice_1014.xml")
    everything = client.get("/api/invoices").json()
    assert everything["total"] == 3 and everything["page"] == 1
    paid = client.get("/api/invoices", params={"status": "paid_mock"}).json()
    assert [i["invoice_number"] for i in paid["items"]] == ["INV-1001"]
    item = paid["items"][0]
    assert item["total"] == "5000.00" and item["currency"] == "USD" and item["mode"] == "offline"
    assert item["vendor_name"] == "Widgets Inc." and item["outcome"] == "paid_mock"
    assert client.get("/api/invoices", params={"mode": "live"}).json()["total"] == 0
    assert client.get("/api/invoices", params={"q": "widgets"}).json()["total"] == 1
    assert client.get("/api/invoices", params={"q": "%"}).json()["total"] == 0
    assert client.get("/api/invoices", params={"page": 2}).json()["items"] == []
    assert client.get("/api/invoices", params={"status": "bogus"}).status_code == 422


def test_invoice_detail_has_every_section(client):
    done = process(client, "invoice_1005.json")[0]
    inv_id = done["result"]["invoice_id"]
    d = client.get(f"/api/invoices/{inv_id}").json()
    assert d["outcome"] == "rejected" and d["mode"] == "offline"
    assert d["invoice"]["invoice_number"] == "INV-1005"
    assert {f["code"] for f in d["findings"]} >= {"quantity_exceeds_stock"}
    stock = {ln["item"]: ln for ln in d["line_items"]}
    assert stock["WidgetA"]["quantity"] == "14" and stock["WidgetA"]["available"] == 15
    assert stock["GadgetX"]["available"] == 5 and stock["GadgetX"]["requested_total"] == "8"
    assert d["decision"]["final_decision"] == "rejected"
    assert d["decision"]["provider"] == "offline" and d["receipt"] is None
    assert [v["version"] for v in d["versions"]] == [1]
    assert d["corrections"] == [] and d["human_reviews"] == [] and d["allowed_actions"] == []
    assert [r["run_id"] for r in d["runs"]] == [done["run_id"]]


def test_invoice_detail_shows_normalization_events_and_receipt(client):
    done = process(client, "invoice_1001.txt")[0]
    d = client.get(f"/api/invoices/{done['result']['invoice_id']}").json()
    assert d["receipt"]["amount"] == "5000.00"
    assert d["normalization_events"] == d["invoice"]["normalization_events"]
    assert d["normalization_events"], "1001 has normalization events"
    for e in d["normalization_events"]:
        assert {"field", "raw_value", "normalized_value", "provenance"} <= set(e)


def test_unknown_invoice_and_source_are_404(client):
    assert client.get("/api/invoices/inv-nope").json()["code"] == "invoice_not_found"
    assert client.get("/api/invoices/inv-nope/result.json").status_code == 404
    assert client.get("/api/sources/src-nope/content").json()["code"] == "source_not_found"


def test_source_content_txt_has_line_anchors(client):
    done = process(client, "invoice_1001.txt")[0]
    src = done["source"]["source_id"]
    body = client.get(f"/api/sources/{src}/content").json()
    assert body["format"] == "txt" and body["original_url"] == f"/api/sources/{src}/original"
    lines = {ln["anchor"]: ln["text"] for ln in body["lines"]}
    assert lines["line:1"] == "INVOICE" and "Vendor: Widgets Inc." in lines["line:3"]
    assert body["rows"] is None


def test_source_content_csv_has_rows_and_pdf_has_pages_and_original(client):
    csv_run, pdf_run = process(client, "invoice_1007.csv", "invoice_1011.pdf")
    csv_body = client.get(f"/api/sources/{csv_run['source']['source_id']}/content").json()
    assert csv_body["rows"][0] == {
        "anchor": "row:1",
        "cells": [
            "Invoice Number",
            "Vendor",
            "Date",
            "Due Date",
            "Item",
            "Qty",
            "Unit Price",
            "Line Total",
        ],
    }
    pdf_id = pdf_run["source"]["source_id"]
    pdf_body = client.get(f"/api/sources/{pdf_id}/content").json()
    assert pdf_body["page_count"] == 1
    assert pdf_body["lines"][0]["anchor"] == "page:1,line:1"
    assert any("INV-1011" in ln["text"] for ln in pdf_body["lines"])
    original = client.get(pdf_body["original_url"])
    assert original.status_code == 200 and original.headers["content-type"] == "application/pdf"
    assert original.content == (SAMPLES / "invoice_1011.pdf").read_bytes()


def test_source_content_falls_back_to_extracted_text_when_original_is_gone(
    client, settings, tmp_path
):
    data = (SAMPLES / "invoice_1001.txt").read_bytes()
    done = wait_done(client, multipart(client, "gone.txt", data).json()["run_id"])
    for p in settings.uploads_dir.rglob("gone.txt"):
        p.unlink()
    src = done["source"]["source_id"]
    body = client.get(f"/api/sources/{src}/content").json()
    assert body["original_url"] is None
    assert client.get(f"/api/sources/{src}/original").status_code == 404


@pytest.mark.parametrize("name", ["invoice_1001.txt", "invoice_1002.txt", "invoice_1014.xml"])
def test_result_json_equals_the_processing_result(client, settings, name):
    # The service run happens outside the API, in the same database the API reads.
    result = process_invoice(SAMPLES / name, ExecutionMode.offline, settings.db_path, EVAL)
    r = client.get(f"/api/invoices/{result.invoice_id}/result.json")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    got = r.json()
    want = result.model_dump(mode="json")
    want.pop("timings_ms")  # stage timings are transient and not persisted
    assert got.pop("timings_ms") == {}
    if want["receipt"]:  # paid_at is stored with microsecond precision, compare as instants
        assert got["receipt"].pop("paid_at") == want["receipt"].pop("paid_at")
    assert got == want


def test_result_json_for_duplicate_path_uses_business_run(client):
    first, _ = process(client, "invoice_1011.txt", "invoice_1011.pdf")
    inv = first["result"]["invoice_id"]
    got = client.get(f"/api/invoices/{inv}/result.json").json()
    assert got["run_id"] == first["run_id"] and got["status"] == "paid_mock"


def test_queued_submissions_are_processed_one_at_a_time(client):
    names = ["invoice_1001.txt", "invoice_1004.json", "invoice_1006.csv", "invoice_1010.txt"]
    run_ids = [submit(client, n).json()["run_id"] for n in names]
    assert len(set(run_ids)) == 4
    assert [wait_done(client, r)["status"] for r in run_ids] == ["paid_mock"] * 4
    starts = [client.get(f"/api/runs/{r}").json() for r in run_ids]
    for a, b in zip(
        starts, starts[1:], strict=False
    ):  # no overlap: each run finished before the next began
        assert a["finished_at"] <= b["started_at"]


# ------------------------------------------------------------------ UI contract (P5-07/P5-08)


def _evidence_locations(detail: dict) -> set[str]:
    refs = [e for f in detail["findings"] for e in f["evidence"]]
    refs += [e for n in detail["normalization_events"] for e in n["evidence"]]
    refs += [e for ln in detail["line_items"] for e in ln["evidence"]]
    src = detail["source"]["source_id"]
    return {e["location"] for e in refs if e["source_id"] == src}


@pytest.mark.parametrize("name", ["invoice_1001.txt", "invoice_1011.pdf", "invoice_1002.txt"])
def test_evidence_locations_equal_source_line_anchors(client, name):
    done = process(client, name)[0]
    d = client.get(f"/api/invoices/{done['result']['invoice_id']}").json()
    body = client.get(f"/api/sources/{d['source']['source_id']}/content").json()
    anchors = {ln["anchor"] for ln in body["lines"]}
    locations = _evidence_locations(d)
    assert locations, "fixture has line-addressed evidence"
    assert locations <= anchors


def test_csv_evidence_rows_resolve_to_row_anchors(client):
    done = process(client, "invoice_1007.csv")[0]
    d = client.get(f"/api/invoices/{done['result']['invoice_id']}").json()
    body = client.get(f"/api/sources/{d['source']['source_id']}/content").json()
    rows = {r["anchor"] for r in body["rows"]}
    row_parts = {loc.split(",")[0] for loc in _evidence_locations(d)}
    assert row_parts and row_parts <= rows


def test_detail_carries_source_run_context_and_latest_result(client):
    done = process(client, "invoice_1001.txt")[0]
    d = client.get(f"/api/invoices/{done['result']['invoice_id']}").json()
    assert d["source"] == {
        "source_id": done["source"]["source_id"],
        "original_name": "invoice_1001.txt",
        "format": "txt",
        "size_bytes": (SAMPLES / "invoice_1001.txt").stat().st_size,
        "page_count": None,
    }
    assert d["evaluation_date"] == EVAL.isoformat()
    assert d["latest_result"] == done["result"]
    (run,) = d["runs"]
    assert run["original_name"] == "invoice_1001.txt"
    assert run["evaluation_date"] == EVAL.isoformat()
    assert run["error_code"] is None and run["retry_of"] is None
    assert run["provider"] == "offline"
    assert run["events"] == done["events"]
    (version,) = d["versions"]
    assert version["original_name"] == "invoice_1001.txt"
    assert version["total"] == "5000.00" and version["currency"] == "USD"
    assert [ln["item"] for ln in version["lines"]] == ["WidgetA", "WidgetB"]
    assert version["receipt"] == d["receipt"]


def test_duplicate_run_exposes_prior_run_in_progress_and_detail(client):
    first, dup = process(client, "invoice_1011.txt", "invoice_1011.pdf")
    assert dup["status"] == "duplicate" and dup["prior_run_id"] == first["run_id"]
    d = client.get(f"/api/invoices/{first['result']['invoice_id']}").json()
    latest = d["runs"][-1]
    assert latest["status"] == "duplicate" and latest["prior_run_id"] == first["run_id"]
    assert latest["original_name"] == "invoice_1011.pdf"
    assert d["latest_result"]["status"] == "duplicate"
    assert d["source"]["original_name"] == "invoice_1011.txt"


def test_pdf_source_reports_pages_and_preview_limitation(client):
    done = process(client, "invoice_1011.pdf")[0]
    d = client.get(f"/api/invoices/{done['result']['invoice_id']}").json()
    assert d["source"]["format"] == "pdf" and d["source"]["page_count"] == 1
    body = client.get(f"/api/sources/{d['source']['source_id']}/content").json()
    assert body["preview_limitation"]
    txt = process(client, "invoice_1001.txt")[0]
    txt_body = client.get(f"/api/sources/{txt['source']['source_id']}/content").json()
    assert txt_body["preview_limitation"] is None


def test_invoice_summary_has_due_date(client):
    process(client, "invoice_1001.txt")
    (item,) = client.get("/api/invoices").json()["items"]
    assert item["due_date"] == "2026-02-01"


def test_committed_openapi_matches_the_app(client):
    """frontend/src/api/openapi.json (and the TS types generated from it) must be current.
    Regenerate: uv run python scripts/export_openapi.py && (cd frontend && npm run gen:api)."""
    import json

    committed = json.loads(Path("frontend/src/api/openapi.json").read_text())
    assert committed == client.get("/openapi.json").json()


def test_openapi_refs_all_resolve(client):
    spec = client.get("/openapi.json").json()
    names = set(spec["components"]["schemas"])

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref is not None:
                assert ref.startswith("#/components/schemas/"), ref
                assert ref.rsplit("/", 1)[1] in names, ref
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(spec)


def test_built_frontend_is_served_with_client_side_route_fallback(settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>ui</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    settings.frontend_dist = dist
    with TestClient(api.create_app(settings)) as c:
        assert c.get("/").text.startswith("<!doctype html>")
        assert c.get("/assets/app.js").text == "console.log(1)"
        for route in ("/invoices/inv-1", "/runs/run-1", "/add"):
            r = c.get(route)
            assert r.status_code == 200 and "<title>ui</title>" in r.text, route
        assert c.get("/assets/missing.js").status_code == 404
        missing_api = c.get("/api/nope")
        assert missing_api.status_code == 404 and missing_api.json()["code"] == "not_found"
        assert c.get("/api/health").json() == {"status": "ok"}


# ------------------------------------------------------------------ P3-08 retry over HTTP

SENTINEL = "sk-SENTINEL-api-retry"


def _rec(decision="approve"):
    return {"recommendation": decision, "reasons": [], "cited_codes": [], "summary": "ok"}


def _crit():
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
    """Live settings with a sentinel key; each xAI client the provider builds takes the
    next script from `scripts`. No network: the fake never opens a channel."""
    import grpc

    from invoice_processing.reasoning import xai
    from tests.fakes.xai_client import FakeXaiClient, Parsed, Raise

    scripts: list[list] = []
    monkeypatch.setenv("XAI_API_KEY", SENTINEL)
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    monkeypatch.setattr(xai, "real_client_factory", lambda s: FakeXaiClient(scripts.pop(0)))
    down = Raise(grpc.StatusCode.UNAVAILABLE)

    class Live:
        def failing(self):
            scripts.append([down, down])

        def working(self):
            scripts.append([Parsed(_rec()), Parsed(_crit())])

    return Live()


def _failed_live_run(client, live, sample="invoice_1001.txt") -> dict:
    live.failing()
    r = submit(client, sample, mode="live")
    assert r.status_code == 202, r.text
    done = wait_done(client, r.json()["run_id"])
    assert done["status"] == "failed", done
    assert done["result"]["recoverable"] is True, (done["error_code"], done["error_message"])
    return done


def retry(client, run_id, key=None, **body):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"/api/runs/{run_id}/retry", json=body or None, headers=headers)


def _paid_count(client) -> int:
    return sum(t["paid_count"] for t in client.get("/api/overview").json()["paid_totals"])


def _run_ids(settings) -> list[str]:
    conn = storage.connect(settings.db_path)
    try:
        return [r["run_id"] for r in conn.execute("SELECT run_id FROM runs ORDER BY started_at")]
    finally:
        conn.close()


def test_retry_creates_a_linked_run_in_the_original_mode_and_pays_once(client, live):
    failed = _failed_live_run(client, live)
    live.working()
    r = retry(client, failed["run_id"])
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["run_id"] != failed["run_id"] and body["mode"] == "live"
    done = wait_done(client, body["run_id"])
    assert done["status"] == "paid_mock" and done["retry_of"] == failed["run_id"]
    assert done["mode_switch_of"] is None
    assert _paid_count(client) == 1
    assert SENTINEL not in r.text + str(done)


def test_retry_offline_runs_a_labeled_separate_simulation(client, live, settings):
    failed = _failed_live_run(client, live)
    r = retry(client, failed["run_id"], action="run_offline")
    assert r.status_code == 202, r.text
    assert r.json()["mode"] == "offline"
    done = wait_done(client, r.json()["run_id"])
    assert done["mode"] == "offline" and done["status"] == "paid_mock"
    assert done["mode_switch_of"] == failed["run_id"] and done["retry_of"] is None


def test_retry_is_idempotent_per_key(client, live, settings):
    failed = _failed_live_run(client, live)
    live.working()
    first = retry(client, failed["run_id"], key="retry-key-1")
    wait_done(client, first.json()["run_id"])
    again = retry(client, failed["run_id"], key="retry-key-1")
    assert again.status_code == 202
    assert again.json()["run_id"] == first.json()["run_id"]
    assert again.json()["idempotent_replay"] is True
    assert len(_run_ids(settings)) == 2


def test_retry_refused_unknown_run(client):
    r = retry(client, "run-nope")
    assert r.status_code == 404
    assert r.json()["code"] == "unknown_run"
    assert r.json()["details"]["reason"] == "unknown_run"


def test_retry_refused_not_failed(client, settings):
    (paid,) = process(client, "invoice_1001.txt")
    r = retry(client, paid["run_id"])
    assert r.status_code == 409
    assert r.json()["code"] == "not_failed" and r.json()["details"]["reason"] == "not_failed"
    assert len(_run_ids(settings)) == 1


def test_retry_refused_not_recoverable(client, settings):
    r = multipart(client, "bad.txt", b"Invoice Number: INV-9\nVendor: Caf\xe9 Ltd\n")
    assert r.status_code == 202, r.text
    failed = wait_done(client, r.json()["run_id"])
    assert failed["error_code"] == "txt_decode_error"
    r = retry(client, failed["run_id"])
    assert r.status_code == 409 and r.json()["code"] == "not_recoverable"
    assert len(_run_ids(settings)) == 1


def test_retry_refused_source_mismatch(client, live, settings, monkeypatch):
    failed = _failed_live_run(client, live)
    # The API locates the original by hash, so a mismatch needs the file to change under it.
    monkeypatch.setattr(api, "_locate_original", lambda s, rec: SAMPLES / "invoice_1002.txt")
    r = retry(client, failed["run_id"])
    assert r.status_code == 409 and r.json()["code"] == "source_mismatch"
    assert len(_run_ids(settings)) == 1


def test_retry_refused_already_paid(client, live, settings):
    failed = _failed_live_run(client, live)
    paid = wait_done(client, retry(client, failed["run_id"], action="run_offline").json()["run_id"])
    assert paid["status"] == "paid_mock"
    r = retry(client, failed["run_id"])
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "already_paid"
    assert body["details"]["receipt_id"] == paid["result"]["receipt"]["receipt_id"]
    assert len(_run_ids(settings)) == 2
    assert _paid_count(client) == 1


def test_retry_offline_refused_for_a_failure_an_offline_run_cannot_fix(client, settings):
    r = multipart(client, "bad.txt", b"Invoice Number: INV-9\nVendor: Caf\xe9 Ltd\n")
    failed = wait_done(client, r.json()["run_id"])
    r = retry(client, failed["run_id"], action="run_offline")
    assert r.status_code == 409 and r.json()["code"] == "not_recoverable"
    assert len(_run_ids(settings)) == 1


def test_retry_live_without_settings_is_provider_unavailable_and_creates_no_run(
    client, live, settings, monkeypatch
):
    failed = _failed_live_run(client, live)
    monkeypatch.delenv("XAI_API_KEY")
    r = retry(client, failed["run_id"])
    assert r.status_code == 409 and r.json()["code"] == "provider_unavailable"
    assert len(_run_ids(settings)) == 1


def test_retry_without_the_original_file_is_refused(client, live, settings, monkeypatch):
    failed = _failed_live_run(client, live)
    monkeypatch.setattr(api, "_locate_original", lambda s, rec: None)
    r = retry(client, failed["run_id"])
    assert r.status_code == 409 and r.json()["code"] == "source_unavailable"
    assert len(_run_ids(settings)) == 1


def test_retry_rejects_an_unknown_action(client, live):
    failed = _failed_live_run(client, live)
    assert retry(client, failed["run_id"], action="pay_anyway").status_code == 422


def test_readiness_uses_phase_3_settings_and_exposes_the_model(client, monkeypatch):
    import invoice_processing.reasoning as reasoning

    def no_provider(*a, **k):
        raise AssertionError("readiness must not build a provider")

    monkeypatch.setattr(reasoning, "get_provider", no_provider)
    monkeypatch.setattr(api, "get_provider", no_provider)
    body = client.get("/api/settings/readiness").json()
    assert body["modes"]["live"]["available"] is False and body["live_model"] is None
    assert "XAI_API_KEY" in body["modes"]["live"]["reason"]
    monkeypatch.setenv("XAI_API_KEY", SENTINEL)
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    r = client.get("/api/settings/readiness")
    body = r.json()
    assert body["modes"]["live"] == {"available": True, "reason": None}
    assert body["live_settings_present"] is True and body["live_model"] == "grok-test"
    assert SENTINEL not in r.text


def test_run_id_comes_from_the_service_hook_not_the_event_log(client, monkeypatch):
    from invoice_processing import observability

    # Even with event logging silenced the API still learns the run id at once.
    monkeypatch.setattr(observability, "log_event", lambda *a, **k: None)
    r = submit(client, "invoice_1001.txt")
    assert r.status_code == 202, r.text
    assert wait_done(client, r.json()["run_id"])["status"] == "paid_mock"


def test_rebuilt_result_recovery_matches_the_service():
    from invoice_processing import queries, service

    assert queries._RECOVERY_ACTIONS == service.RECOVERY_ACTIONS
    retryable = {c for c in service.RETRYABLE_ERROR_CODES if queries.next_actions_for(c)}
    assert retryable == set(service.RETRYABLE_ERROR_CODES)
    assert queries.next_actions_for("txt_decode_error") == []
    assert queries.next_actions_for(None) == []


def test_live_failure_result_over_http_matches_the_service_result(client, live):
    failed = _failed_live_run(client, live)
    assert failed["result"]["next_actions"] == ["retry", "run offline as a separate simulation"]
    assert failed["result"]["model_calls_used"] == 2  # one step, its transport retry charged


def test_detail_allows_retry_only_for_a_recoverable_latest_failure(client, live):
    failed = _failed_live_run(client, live)
    assert failed["invoice_id"], "1001 is extracted before the model fails"
    detail = client.get(f"/api/invoices/{failed['invoice_id']}").json()
    assert detail["allowed_actions"] == ["retry"]
    live.working()
    wait_done(client, retry(client, failed["run_id"]).json()["run_id"])
    detail = client.get(f"/api/invoices/{failed['invoice_id']}").json()
    assert detail["allowed_actions"] == []


def test_service_on_run_started_hook_reports_the_run_once_before_work(tmp_path):
    from invoice_processing import ledger as ledger_mod

    db = tmp_path / "hook.db"
    seen: list[tuple[str, str]] = []

    def hook(run_id: str) -> None:
        conn = storage.connect(db)
        try:
            seen.append((run_id, ledger_mod.get_run_status(conn, run_id).value))
        finally:
            conn.close()

    result = process_invoice(
        SAMPLES / "invoice_1001.txt", ExecutionMode.offline, db, EVAL, on_run_started=hook
    )
    assert seen == [(result.run_id, "received")]
