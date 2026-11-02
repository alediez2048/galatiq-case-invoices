"""Reasoning providers: the offline simulator and the live xAI provider."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from invoice_processing.codes import ExecutionMode
from invoice_processing.reasoning.base import PolicyContext, ReasoningProvider
from invoice_processing.reasoning.errors import ModelError, ProviderUnavailable
from invoice_processing.reasoning.session import ModelSession

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
        from invoice_processing.reasoning import xai  # lazy: offline never loads the adapter
        from invoice_processing.settings import load_live_settings  # lazy: avoids a cycle

        settings = settings or load_live_settings()
        return xai.XaiProvider(settings, client_factory or xai.real_client_factory)
    from invoice_processing.reasoning.offline import OfflineSimulator

    return OfflineSimulator()


__all__ = [
    "ModelError",
    "ModelSession",
    "PolicyContext",
    "ProviderUnavailable",
    "ReasoningProvider",
    "get_provider",
]
