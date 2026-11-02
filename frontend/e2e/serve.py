"""Test-only server for the Playwright suite (frontend/e2e).

Serves the built UI (frontend/dist) and the API from a throwaway SQLite database in a
temporary directory, in offline mode: no credentials are read and no external service is
called. The repo-root inventory.db and data/invoices/ are never written.

    uv run python frontend/e2e/serve.py --port 18765
"""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from invoice_processing.api import ApiSettings, create_app  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=18765)
    args = p.parse_args()
    for var in ("XAI_API_KEY", "XAI_MODEL"):
        os.environ.pop(var, None)  # offline only, whatever the developer's shell holds
    tmp = Path(tempfile.mkdtemp(prefix="galatiq-e2e-"))
    try:
        app = create_app(
            ApiSettings(
                db_path=tmp / "e2e.db",
                uploads_dir=tmp / "uploads",
                frontend_dist=ROOT / "frontend" / "dist",
            )
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
