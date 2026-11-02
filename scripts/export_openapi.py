"""Write the API's OpenAPI schema for the typed frontend client.

Usage: uv run python scripts/export_openapi.py [output.json]
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from invoice_processing.api import ApiSettings, create_app  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "frontend/src/api/openapi.json"
    with tempfile.TemporaryDirectory() as tmp:  # never touches inventory.db
        app = create_app(
            ApiSettings(db_path=Path(tmp) / "openapi.db", uploads_dir=Path(tmp) / "up")
        )
        spec = app.openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
