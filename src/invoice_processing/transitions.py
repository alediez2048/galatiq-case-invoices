"""Legal run-status transitions. Terminal statuses have no outgoing edges."""

from invoice_processing.codes import TERMINAL_RUN_STATUSES, RunStatus

S = RunStatus

RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    S.received: frozenset({S.extracted, S.failed, S.duplicate}),
    S.extracted: frozenset({S.validated, S.failed}),
    S.validated: frozenset({S.approval_pending, S.failed}),
    S.approval_pending: frozenset(
        {S.approved, S.rejected, S.needs_review, S.awaiting_human_approval, S.failed}
    ),
    S.approved: frozenset({S.paid_mock, S.failed}),
    **{status: frozenset[RunStatus]() for status in TERMINAL_RUN_STATUSES},
}


class IllegalTransition(ValueError):
    pass


def check(current: RunStatus, new: RunStatus) -> None:
    if new not in RUN_TRANSITIONS[current]:
        raise IllegalTransition(f"illegal run transition: {current.value} -> {new.value}")
