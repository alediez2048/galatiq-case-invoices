"""Reasoning providers. Offline is the only mode available before Phase 3."""

from invoice_processing.codes import ExecutionMode
from invoice_processing.reasoning.base import PolicyContext, ReasoningProvider


class ProviderUnavailable(RuntimeError):
    """The requested reasoning provider cannot be used."""


def get_provider(mode: ExecutionMode | str) -> ReasoningProvider:
    try:
        resolved = ExecutionMode(mode)
    except ValueError:
        raise ValueError(f"unknown execution mode: {mode!r}") from None
    if resolved is ExecutionMode.live:
        raise ProviderUnavailable("live mode is not available until Phase 3")
    from invoice_processing.reasoning.offline import OfflineSimulator

    return OfflineSimulator()


__all__ = ["PolicyContext", "ProviderUnavailable", "ReasoningProvider", "get_provider"]
