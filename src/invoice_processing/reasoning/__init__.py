"""Reasoning providers: the offline simulator and the live xAI provider."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from invoice_processing.codes import ExecutionMode
from invoice_processing.reasoning.base import PolicyContext, ReasoningProvider
from invoice_processing.reasoning.errors import ProviderUnavailable

if TYPE_CHECKING:
    from invoice_processing.settings import LiveSettings


def get_provider(
    mode: ExecutionMode | str,
    *,
    settings: "LiveSettings | None" = None,
    client_factory: Callable[["LiveSettings"], Any] | None = None,
) -> ReasoningProvider:
    try:
        resolved = ExecutionMode(mode)
    except ValueError:
        raise ValueError(f"unknown execution mode: {mode!r}") from None
    if resolved is ExecutionMode.live:
        from invoice_processing.settings import load_live_settings  # lazy: avoids a cycle

        settings = settings or load_live_settings()
        raise ProviderUnavailable("live provider arrives in Task 2")
    from invoice_processing.reasoning.offline import OfflineSimulator

    return OfflineSimulator()


__all__ = ["PolicyContext", "ProviderUnavailable", "ReasoningProvider", "get_provider"]
