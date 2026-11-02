"""The review queue (Decision 21) and its allowed actions, which must agree with what each
review action actually refuses."""

from pathlib import Path

import pytest

from invoice_processing import review, storage
from invoice_processing.codes import InvoiceStatus, QueueGroup, ReviewAction
from invoice_processing.schemas import CorrectionRequest, FieldChange, QueueItem
from tests.review_helpers import EVAL, INVOICES, REVIEW, process, seeded_db

THRESHOLD = Path(__file__).resolve().parent / "fixtures" / "threshold"
FILES = [
    INVOICES / "invoice_1001.txt",
    INVOICES / "invoice_1003.txt",
    INVOICES / "invoice_1014.xml",
    REVIEW / "extraction_mistake.txt",
    THRESHOLD / "valid_10000_01.json",
]


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    path = seeded_db(tmp_path_factory.mktemp("queue"))
    for f in FILES:
        process(f, path)
    return path


def item(q, group: QueueGroup, number: str) -> QueueItem:
    (found,) = [i for i in q.groups[group] if i.invoice_number == number]
    return found


def test_queue_groups(db):
    q = review.list_queue(db_path=db)
    assert set(q.groups) == set(QueueGroup)
    eur = item(q, QueueGroup.unresolved_blocker, "INV-1014")
    assert ReviewAction.approve not in eur.actions.allowed
    assert eur.actions.refused[ReviewAction.approve] == "action_not_allowed"
    assert eur.status is InvoiceStatus.needs_review and eur.currency == "EUR"
    hv = item(q, QueueGroup.awaiting_human_approval, "TH-10000-01")
    assert {ReviewAction.approve, ReviewAction.decline} <= set(hv.actions.allowed)
    assert str(hv.total) == "10000.01" and hv.current_version == 1
    ct = item(q, QueueGroup.correctable_extraction, "CT-3001")
    assert ct.reason_codes == ["unparseable_value"]
    assert ct.vendor_name == "Correction Test Co"
    assert not any(
        i.invoice_number in {"INV-1001", "INV-1003"} for g in q.groups.values() for i in g
    )
    assert sum(len(g) for g in q.groups.values()) == 3


def test_reason_codes_sorted_and_unique(db):
    q = review.list_queue(db_path=db)
    for group in q.groups.values():
        for i in group:
            assert i.reason_codes == sorted(set(i.reason_codes))
    eur = item(q, QueueGroup.unresolved_blocker, "INV-1014")
    assert {"non_usd_currency", "unsupported_currency"} <= set(eur.reason_codes)


def test_queue_items_ordered_by_updated_at(db):
    q = review.list_queue(db_path=db)
    conn = storage.connect(db)
    try:
        updated = dict(conn.execute("SELECT invoice_id, updated_at FROM invoices").fetchall())
    finally:
        conn.close()
    for group in q.groups.values():
        stamps = [updated[i.invoice_id] for i in group]
        assert stamps == sorted(stamps)


def test_empty_queue(tmp_path):
    q = review.list_queue(db_path=seeded_db(tmp_path))
    assert q.groups == {g: [] for g in QueueGroup}


def _call(action: ReviewAction, i: QueueItem, db: Path) -> None:
    version = i.current_version
    if action is ReviewAction.correct:
        request = CorrectionRequest(
            invoice_id=i.invoice_id,
            expected_version=version,
            changes=[FieldChange(field="due_date", new_value="2026-03-01", evidence_location="x")],
            reason="r",
            reviewer="Ana",
        )
        review.submit_correction(request, db_path=db)
    elif action is ReviewAction.approve:
        review.approve(i.invoice_id, version, "Ana", "r", db_path=db)
    elif action is ReviewAction.decline:
        review.decline(i.invoice_id, version, "Ana", "r", db_path=db)
    else:
        review.submit_corrected_invoice(
            i.invoice_id,
            REVIEW / "inv_1013_corrected.json",
            "r",
            "Ana",
            db_path=db,
            evaluation_date=EVAL,
        )


def test_allowed_actions_matches_service_refusals(db):
    q = review.list_queue(db_path=db)
    checked = 0
    for group in q.groups.values():
        for i in group:
            assert set(i.actions.allowed) | set(i.actions.refused) == set(ReviewAction)
            for action, code in i.actions.refused.items():
                with pytest.raises(review.ReviewRefused) as e:
                    _call(action, i, db)
                assert e.value.code == code, (i.invoice_number, action)
                checked += 1
    assert checked >= 5
    # Nothing was written by the refusals: the queue is unchanged.
    assert review.list_queue(db_path=db) == q
