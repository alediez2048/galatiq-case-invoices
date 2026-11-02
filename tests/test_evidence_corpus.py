"""Corpus-wide Decision 8 guard: no other spelling of another field's evidence can be cited."""

from datetime import date
from pathlib import Path

import pytest

from invoice_processing import evidence, ledger, seed, storage
from invoice_processing.codes import ExecutionMode
from invoice_processing.service import process_invoice

ROOT = Path(__file__).resolve().parent.parent
CORPUS = sorted((ROOT / "data" / "invoices").iterdir()) + sorted(
    (ROOT / "tests" / "fixtures" / "review").glob("*.[jtx][sxm]*")
)


def _candidates(text: str) -> list[str]:
    """Every line, page-line and row spelling that could address this text."""
    lines = len(text.splitlines())
    pages = text.split("\n\f\n")
    out = [f"line:{n}" for n in range(1, lines + 1)]
    out += [f"row:{n}" for n in range(1, lines + 1)]
    out += [
        f"page:{p},line:{n}"
        for p, page in enumerate(pages, start=1)
        for n in range(1, len(page.splitlines()) + 1)
    ]
    return out


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.name)
def test_no_cross_scheme_spelling_reaches_another_fields_evidence(tmp_path, path):
    db = tmp_path / "c.db"
    conn = storage.connect(db)
    storage.init_schema(conn)
    seed.seed_inventory(conn)
    conn.close()
    result = process_invoice(path, ExecutionMode.offline, db, date(2026, 1, 31))
    conn = storage.connect(db)
    try:
        invoice = ledger.get_version(conn, result.invoice_id, result.version)
        source = ledger.get_source(conn, invoice.source_id)
    finally:
        conn.close()
    inv, text, fmt = invoice.invoice, source.extracted_text, source.format
    owned = [(name, ref.location) for name, refs in inv.field_evidence.items() for ref in refs]
    owned += [
        (f"lines[{i}]", r.location) for i, line in enumerate(inv.lines) for r in line.evidence
    ]
    for owner, recorded in owned:
        target = evidence.locate(text, recorded)
        if not target or not target.strip():
            continue
        field = "due_date" if owner == "total" else "stated.total"
        for cited in _candidates(text):
            if evidence.locate(text, cited) != target:
                continue
            # what review accepts: the right scheme, and not another field's location
            accepted = evidence.scheme_matches(cited, fmt) and not evidence.claimed_by_other(
                field, cited, inv, text
            )
            assert not accepted, (path.name, owner, recorded, cited)
