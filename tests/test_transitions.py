import pytest

from invoice_processing.codes import TERMINAL_RUN_STATUSES, RunStatus
from invoice_processing.transitions import RUN_TRANSITIONS, IllegalTransition, check

S = RunStatus


@pytest.mark.parametrize(
    ("cur", "new"),
    [(S.paid_mock, s) for s in S]
    + [(S.duplicate, S.paid_mock), (S.received, S.paid_mock), (S.validated, S.approved)],
)
def test_illegal_transitions_raise(cur, new):
    with pytest.raises(IllegalTransition):
        check(cur, new)


def test_happy_path_transitions_are_legal():
    path = [S.received, S.extracted, S.validated, S.approval_pending, S.approved, S.paid_mock]
    for cur, new in zip(path, path[1:], strict=False):
        check(cur, new)


def test_failed_is_legal_from_every_non_terminal_state():
    for status in S:
        if status not in TERMINAL_RUN_STATUSES:
            check(status, S.failed)


def test_terminal_statuses_have_no_exits():
    for status in TERMINAL_RUN_STATUSES:
        assert RUN_TRANSITIONS[status] == frozenset()


def test_extracted_to_duplicate_is_legal():
    check(S.extracted, S.duplicate)
