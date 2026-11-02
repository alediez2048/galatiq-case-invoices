from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoice_processing.codes import (
    HumanReviewAction,
    InvoiceStatus,
    QueueGroup,
    ReviewAction,
    ReviewRefusal,
)
from invoice_processing.schemas import (
    AllowedActions,
    ApprovalDecision,
    Correction,
    CorrectionRequest,
    FieldChange,
    HumanReview,
    NormalizedInvoice,
    ProcessingResult,
    QueueItem,
    ReviewQueue,
    SupersedeLink,
)


def change(field="stated.total", new_value="1.00", evidence_location="line:1"):
    return FieldChange(field=field, new_value=new_value, evidence_location=evidence_location)


def request(**overrides):
    fields = {
        "invoice_id": "inv-1",
        "expected_version": 1,
        "changes": [change()],
        "reason": "Total misread",
        "reviewer": "Ana",
    }
    fields.update(overrides)
    return CorrectionRequest(**fields)


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_blank_reason_rejected(reason):
    with pytest.raises(ValidationError):
        request(reason=reason)


@pytest.mark.parametrize("reviewer", ["", "   ", "x" * 101])
def test_blank_or_long_reviewer_rejected(reviewer):
    with pytest.raises(ValidationError):
        request(reviewer=reviewer)


def test_reviewer_and_reason_are_stripped_and_bounded():
    req = request(reviewer="  Ana  ", reason=" ok ")
    assert (req.reviewer, req.reason) == ("Ana", "ok")
    assert request(reviewer="x" * 100, reason="y" * 1000).reviewer == "x" * 100
    with pytest.raises(ValidationError):
        request(reason="y" * 1001)


@pytest.mark.parametrize(
    "field",
    [
        "vendor",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "stated.subtotal",
        "stated.tax",
        "stated.shipping",
        "stated.total",
        "lines[0].item",
        "lines[2].unit_price",
        "lines[12].quantity",
        "lines[1].line_total",
    ],
)
def test_correctable_field_paths_accepted(field):
    assert change(field=field).field == field


@pytest.mark.parametrize(
    "field",
    [
        "line_items[2].unit_price",
        "stated.amount",
        "stated.tax_rate",
        "lines[].item",
        "lines[x].item",
        "lines[1].note",
        "vendor_key",
        "Vendor",
        " vendor",
        "vendor\n",
    ],
)
def test_other_field_paths_rejected(field):
    with pytest.raises(ValidationError):
        change(field=field)


@pytest.mark.parametrize(
    "overrides",
    [{"new_value": ""}, {"new_value": "   "}, {"new_value": "9" * 201}, {"evidence_location": ""}],
)
def test_change_value_and_location_bounds(overrides):
    with pytest.raises(ValidationError):
        change(**overrides)


def test_new_value_is_stripped():
    assert change(new_value="  12.50 ").new_value == "12.50"


def test_duplicate_fields_in_one_request_rejected():
    with pytest.raises(ValidationError):
        request(changes=[change(), change(new_value="2.00")])


@pytest.mark.parametrize("n", [0, 11])
def test_change_count_bounds(n):
    changes = [change(field=f"lines[{i}].item", new_value="WidgetA") for i in range(n)]
    with pytest.raises(ValidationError):
        request(changes=changes)


def test_ten_distinct_changes_accepted():
    changes = [change(field=f"lines[{i}].item", new_value="WidgetA") for i in range(10)]
    assert len(request(changes=changes).changes) == 10


@pytest.mark.parametrize("version", [0, -1])
def test_expected_version_must_be_positive(version):
    with pytest.raises(ValidationError):
        request(expected_version=version)


def human_review(**overrides):
    fields = {
        "invoice_id": "inv-1",
        "version": 1,
        "action": HumanReviewAction.approve,
        "reviewer": "Ana",
        "reason": "Checked with vendor",
        "policy_version": "p1",
    }
    fields.update(overrides)
    return HumanReview(**fields)


@pytest.mark.parametrize("overrides", [{"reason": "  "}, {"reviewer": ""}, {"reviewer": "x" * 101}])
def test_human_review_reason_and_reviewer_required(overrides):
    with pytest.raises(ValidationError):
        human_review(**overrides)


def test_human_review_created_at_optional():
    assert human_review().created_at is None
    at = datetime(2026, 1, 31, tzinfo=UTC)
    assert human_review(created_at=at).created_at == at


def test_correction_record():
    c = Correction(
        invoice_id="inv-1",
        base_version=1,
        field="stated.total",
        old_value=None,
        new_value="1.00",
        evidence_location="line:1",
        reviewer="Ana",
        reason="r",
        created_at=datetime(2026, 1, 31, tzinfo=UTC),
        resulting_version=2,
    )
    assert c.resulting_version == 2
    with pytest.raises(ValidationError):
        c.model_validate({**c.model_dump(), "reason": " "})


def test_allowed_actions_and_queue_contracts():
    actions = AllowedActions(
        invoice_id="inv-1",
        status=InvoiceStatus.needs_review,
        current_version=1,
        allowed=[ReviewAction.correct],
        refused={ReviewAction.approve: ReviewRefusal.action_not_allowed},
    )
    item = QueueItem(
        invoice_id="inv-1",
        vendor_name="Widgets Inc.",
        invoice_number="INV-1",
        total=Decimal("1.00"),
        currency="USD",
        status=InvoiceStatus.needs_review,
        current_version=1,
        reason_codes=["ambiguous_date"],
        actions=actions,
    )
    queue = ReviewQueue(groups={QueueGroup.correctable_extraction: [item]})
    assert list(queue.groups) == list(QueueGroup)
    assert queue.groups[QueueGroup.unresolved_blocker] == []
    assert ReviewQueue().groups == {g: [] for g in QueueGroup}
    dumped = queue.model_dump(mode="json")
    assert dumped["groups"]["correctable_extraction"][0]["total"] == "1.00"


def test_supersede_link_requires_reason_and_reviewer():
    assert SupersedeLink(invoice_id="inv-1", reviewer=" Ana ", reason="r").reviewer == "Ana"
    with pytest.raises(ValidationError):
        SupersedeLink(invoice_id="inv-1", reviewer="Ana", reason="")


def test_optional_fields_on_existing_contracts():
    assert "human_review" in ApprovalDecision.model_fields
    assert ApprovalDecision.model_fields["human_review"].default is None
    assert ProcessingResult.model_fields["version"].default is None
    assert NormalizedInvoice(source_id="s").field_evidence == {}
