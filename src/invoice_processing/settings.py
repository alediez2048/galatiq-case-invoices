"""Live-mode configuration. Loaded only for `--mode live`; the key is never shown."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from invoice_processing.reasoning.errors import ProviderUnavailable


class ConfigurationError(ProviderUnavailable):
    """Live settings are missing or invalid. Names variables, never their values."""


@dataclass(frozen=True)
class LiveSettings:
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: float = 30.0
    call_budget: int = 6
    tool_turn_cap: int = 3
    excerpt_chars: int = 4000

    def __repr__(self) -> str:
        return (
            f"LiveSettings(api_key='***', model={self.model!r}, "
            f"timeout_seconds={self.timeout_seconds}, call_budget={self.call_budget}, "
            f"tool_turn_cap={self.tool_turn_cap}, excerpt_chars={self.excerpt_chars})"
        )

    __str__ = __repr__


def load_dotenv_file() -> None:
    """Load `.env` (searched upward from the cwd) without overriding set variables.

    The single place `.env` is read; tests replace it so a developer's real key never
    reaches the suite.
    """
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True), override=False)


def load_live_settings(env: Mapping[str, str] | None = None) -> LiveSettings:
    if env is None:
        load_dotenv_file()
        env = os.environ
    api_key = (env.get("XAI_API_KEY") or "").strip()
    model = (env.get("XAI_MODEL") or "").strip()
    missing = [n for n, v in (("XAI_API_KEY", api_key), ("XAI_MODEL", model)) if not v]
    if missing:
        raise ConfigurationError(
            "live mode needs " + " and ".join(missing) + " (set in the environment or .env)"
        )
    timeout = 30.0
    raw_timeout = (env.get("XAI_TIMEOUT_SECONDS") or "").strip()
    if raw_timeout:
        try:
            timeout = float(raw_timeout)
        except ValueError:
            timeout = math.nan
        if not math.isfinite(timeout) or timeout <= 0:
            raise ConfigurationError("XAI_TIMEOUT_SECONDS must be a positive number")
    budget = 6
    raw_budget = (env.get("MODEL_CALL_BUDGET") or "").strip()
    if raw_budget:
        try:
            budget = int(raw_budget)
        except ValueError:
            budget = 0
        if budget < 1:
            raise ConfigurationError("MODEL_CALL_BUDGET must be a positive integer")
    return LiveSettings(api_key=api_key, model=model, timeout_seconds=timeout, call_budget=budget)
