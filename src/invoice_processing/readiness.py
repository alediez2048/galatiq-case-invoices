"""Live-mode readiness check: python -m invoice_processing.readiness [--ping]."""

import argparse
import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass

from invoice_processing import settings as settings_module
from invoice_processing.settings import ConfigurationError, LiveSettings, load_live_settings


def _ping(settings: LiveSettings) -> str:
    """One minimal call through the same client factory the live provider uses."""
    from invoice_processing.reasoning import xai  # lazy: the only path that may touch the network
    from invoice_processing.reasoning.errors import classify

    try:
        client = xai.real_client_factory(settings)
        chat = client.chat.create(model=settings.model, max_tokens=1)
        from xai_sdk.chat import user

        chat.append(user("ping"))
        started = time.perf_counter()
        chat.sample()
        ms = round((time.perf_counter() - started) * 1000)
        return f"ping: ok ({settings.model}, {ms} ms)"
    except Exception as exc:  # report a code only; messages could echo request details
        return f"ping: failed ({classify(exc).code.value})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check live-mode (xAI) configuration.")
    parser.add_argument("--ping", action="store_true", help="make one minimal SDK call")
    args = parser.parse_args(argv)

    settings_module.load_dotenv_file()
    env = os.environ
    print(f"XAI_API_KEY: {'set' if (env.get('XAI_API_KEY') or '').strip() else 'missing'}")
    print(f"XAI_MODEL: {(env.get('XAI_MODEL') or '').strip() or 'missing'}")
    try:
        settings = load_live_settings(env)
    except ConfigurationError as exc:
        print(f"not ready: {exc}")
        return 2
    print(f"XAI_TIMEOUT_SECONDS: {settings.timeout_seconds}")
    print(f"MODEL_CALL_BUDGET: {settings.call_budget}")
    if args.ping:
        line = _ping(settings)
        print(line)
        return 0 if line.startswith("ping: ok") else 2
    return 0


@dataclass(frozen=True)
class LiveStatus:
    """Configuration-only live readiness: never imports the SDK or opens a socket."""

    available: bool
    model: str | None = None
    reason: str | None = None


def live_status(env: Mapping[str, str] | None = None) -> LiveStatus:
    """What the API and UI show for live mode. The key itself is never returned."""
    try:
        settings = load_live_settings(env)
    except ConfigurationError as exc:
        return LiveStatus(available=False, reason=str(exc))
    return LiveStatus(available=True, model=settings.model)


if __name__ == "__main__":
    sys.exit(main())
