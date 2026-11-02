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
        if body["terminal"]:
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
    for name, schema in spec["components"]["schemas"].items():
        for prop in schema.get("properties", {}):
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
