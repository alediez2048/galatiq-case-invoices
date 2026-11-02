"""Capture real API responses as frontend test fixtures (wire shape, not hand-written).

Processes a few bundled samples offline on a throwaway database and writes the responses the
UI consumes to frontend/src/test/real/*.json, so adapter and view tests run against what the
backend actually returns. Never touches inventory.db.

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


def _wait(client: TestClient, run_id: str) -> dict:
    for _ in range(600):
        body = client.get(f"/api/runs/{run_id}").json()
        if body["terminal"]:
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
        with TestClient(create_app(settings)) as client, contextlib.redirect_stdout(io.StringIO()):
            for key, sample in SAMPLES.items():
                accepted = client.post("/api/runs", json={"sample": sample, "mode": "offline"})
                run = _wait(client, accepted.json()["run_id"])
                detail = client.get(f"/api/invoices/{run['invoice_id']}").json()
                source = client.get(f"/api/sources/{detail['source']['source_id']}/content").json()
                for kind, body in (("run", run), ("detail", detail), ("source", source)):
                    path = OUT / f"{kind}-{key}.json"
                    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(SAMPLES) * 3} fixtures to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
