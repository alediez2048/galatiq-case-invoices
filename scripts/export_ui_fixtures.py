"""Capture real API responses as frontend test fixtures (wire shape, not hand-written).

Processes a few bundled samples offline on a throwaway database and writes the responses the
UI consumes to frontend/src/test/real/*.json, so adapter and view tests run against what the
backend actually returns. Also records review-action bodies (P5-04): a correction's and an
approval's 202, the approval run once paid, the review queue, the 409 for a stale version
and a 422 refusal. Never touches inventory.db.

Usage: uv run python scripts/export_ui_fixtures.py
"""

import contextlib
import io
import json
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from invoice_processing.api import ApiSettings, create_app  # noqa: E402

OUT = ROOT / "frontend/src/test/real"
EVALUATION_DATE = date(2026, 1, 31)
SAMPLES = {"1001": "invoice_1001.txt", "1011pdf": "invoice_1011.pdf", "1007": "invoice_1007.csv"}
OCR_AMBIGUOUS = ROOT / "tests/fixtures/review/ocr_ambiguous.txt"  # needs_review, line 9 misread
HIGH_VALUE = ROOT / "tests/fixtures/threshold/valid_10000_01.json"  # awaiting_human_approval


def _wait(client: TestClient, run_id: str) -> dict:
    for _ in range(600):
        body = client.get(f"/api/runs/{run_id}").json()
        # The status turns terminal just before the service's closing event is written.
        if body["terminal"] and any(e["stage"] == "service" for e in body["events"]):
            return body
        time.sleep(0.05)
    raise RuntimeError(f"run {run_id} did not finish")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        settings = ApiSettings(
            db_path=Path(tmp) / "fixtures.db",
            uploads_dir=Path(tmp) / "uploads",
            frontend_dist=Path(tmp) / "no-dist",
            evaluation_date=EVALUATION_DATE,
        )
        # A loopback base URL: the app trusts loopback Host names only (not "testserver").
        app = create_app(settings)
        with (
            TestClient(app, base_url="http://127.0.0.1") as client,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            for key, sample in SAMPLES.items():
                accepted = client.post(
                    "/api/runs",
                    json={"sample": sample, "mode": "offline"},
                    headers={"Idempotency-Key": f"fixture-run-{key}"},
                )
                run = _wait(client, accepted.json()["run_id"])
                detail = client.get(f"/api/invoices/{run['invoice_id']}").json()
                source = client.get(f"/api/sources/{detail['source']['source_id']}/content").json()
                for kind, body in (("run", run), ("detail", detail), ("source", source)):
                    _write(f"{kind}-{key}", body)
            _review_bodies(client)
    print(f"wrote {len(SAMPLES) * 3 + 6} fixtures to {OUT.relative_to(ROOT)}")


def _write(name: str, body: dict) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


def _correct(client: TestClient, invoice_id: str, body: dict, key: str):
    return client.post(
        f"/api/invoices/{invoice_id}/corrections", json=body, headers={"Idempotency-Key": key}
    )


def _upload(client: TestClient, path: Path, media: str) -> str:
    """Process an upload offline; its invoice id."""
    upload = {"file": (path.name, path.read_bytes(), media)}
    accepted = client.post(
        "/api/runs",
        files=upload,
        data={"mode": "offline"},
        headers={"Idempotency-Key": f"fixture-upload-{path.name}"},
    )
    return _wait(client, accepted.json()["run_id"])["invoice_id"]


def _review_bodies(client: TestClient) -> None:
    invoice_id = _upload(client, OCR_AMBIGUOUS, "text/plain")
    correction = {
        "expected_version": 1,
        "changes": [
            {"field": "lines[0].line_total", "new_value": "3500.00", "evidence_location": "line:9"}
        ],
        "reason": "OCR misread the line total",
        "reviewer": "Ana",
    }
    ok = _correct(client, invoice_id, correction, "fixture-correction")
    _wait(client, ok.json()["run_id"])
    stale = _correct(client, invoice_id, correction, "fixture-stale")  # still says version 1
    refused = _correct(
        client,
        invoice_id,
        {
            **correction,
            "expected_version": 2,
            "changes": [{**correction["changes"][0], "new_value": "3150.00"}],
        },
        "fixture-refused",
    )
    high = _upload(client, HIGH_VALUE, "application/json")
    _write("review-queue", client.get("/api/review-queue").json())
    approve = client.post(
        f"/api/invoices/{high}/approve",
        json={"expected_version": 1, "reason": "Verified with the vendor", "reviewer": "Ana"},
        headers={"Idempotency-Key": "fixture-approve"},
    )
    _write("run-approve", _wait(client, approve.json()["run_id"]))
    for name, response, status in (
        ("review-correction", ok, 202),
        ("review-approve", approve, 202),
        ("review-stale-409", stale, 409),
        ("review-refused-422", refused, 422),
    ):
        if response.status_code != status:
            raise RuntimeError(f"{name}: {response.status_code} {response.text}")
        _write(name, response.json())


if __name__ == "__main__":
    main()
