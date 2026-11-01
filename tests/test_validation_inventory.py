from decimal import Decimal

from invoice_processing import seed, storage, validation
from invoice_processing.codes import FindingCode as C
from tests.helpers import codes, inv_1001, inv_1013, line

SEED = dict(seed.SEED_ITEMS)


def test_1013_aggregates_and_exceeds():
    agg = validation.aggregate_quantities(inv_1013().lines)
    assert {k: v.quantity for k, v in agg.items()} == {
        "WidgetA": Decimal("22"),
        "WidgetB": Decimal("18"),
        "GadgetX": Decimal("9"),
    }
    assert agg["WidgetA"].line_indexes == [0, 3, 6]
    f = validation.check_inventory(agg, SEED)
    assert codes(f) == [C.quantity_exceeds_stock] * 3


def test_1002_gadgetx_exceeds():
    agg = validation.aggregate_quantities([line("GadgetX", "20", "750")])
    [f] = validation.check_inventory(agg, SEED)
    assert f.code == C.quantity_exceeds_stock and f.observed == "20" and f.expected == "5"


def test_zero_and_unknown():
    agg = validation.aggregate_quantities(
        [
            line("FakeItem", "100", "1000"),
            line("SuperGizmo", "12", "400"),
            line("WidgetC", "3", "350"),
        ]
    )
    f = {x.item: x.code for x in validation.check_inventory(agg, SEED)}
    assert f == {"FakeItem": C.zero_stock, "SuperGizmo": C.unknown_item, "WidgetC": C.unknown_item}


def test_1001_within_stock():
    assert validation.check_inventory(validation.aggregate_quantities(inv_1001().lines), SEED) == []


def test_quantity_equal_to_stock_passes():
    agg = validation.aggregate_quantities([line("GadgetX", "5", "750")])
    assert validation.check_inventory(agg, SEED) == []


def test_case_and_whitespace_variants_are_unknown():
    agg = validation.aggregate_quantities([line("widgeta", "1", "1"), line("Widget A", "1", "1")])
    assert [x.code for x in validation.check_inventory(agg, SEED)] == [
        C.unknown_item,
        C.unknown_item,
    ]


def test_lines_without_item_or_quantity_are_skipped():
    agg = validation.aggregate_quantities([line(None, "1", "1"), line("WidgetA", None, "1")])
    assert agg == {}


def test_against_db_does_not_change_stock(conn):
    seed.seed_inventory(conn)
    f = validation.check_inventory_against_db(
        conn, validation.aggregate_quantities(inv_1013().lines)
    )
    assert len(f) == 3
    assert storage.get_stock(conn, seed.SEED_ITEMS) == seed.SEED_ITEMS
