import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = """
import sys
sys.path.insert(0, {root!r})
import main
code = main.main(["--invoice_path=data/invoices/invoice_1001.txt", "--db={db}",
                  "--events={ev}", "--evaluation-date=2026-01-20", "--output={out}"])
assert code == 0, code
assert "xai_sdk" not in sys.modules, "xai_sdk imported in offline mode"
"""


def test_offline_run_never_imports_xai_sdk(tmp_path):
    script = SCRIPT.format(
        root=str(ROOT), db=tmp_path / "i.db", ev=tmp_path / "e.jsonl", out=tmp_path / "o.json"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "INVOICE_NETWORK_GUARD": "1"},
    )
    assert proc.returncode == 0, proc.stderr
