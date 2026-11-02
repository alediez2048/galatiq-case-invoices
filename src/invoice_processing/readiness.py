"""Live-mode readiness check: python -m invoice_processing.readiness [--ping]."""

import argparse
import os
import sys
import time

from invoice_processing import settings as settings_module
from invoice_processing.settings import ConfigurationError, load_live_settings


def _ping(api_key: str, model: str, timeout: float) -> str:
    try:
        from xai_sdk import Client  # lazy: the only path that may touch the network

        client = Client(api_key=api_key, timeout=timeout)
        chat = client.chat.create(model=model, max_tokens=1)
        from xai_sdk.chat import user

        chat.append(user("ping"))
        started = time.perf_counter()
        chat.sample()
        ms = round((time.perf_counter() - started) * 1000)
        return f"ping: ok ({model}, {ms} ms)"
    except Exception as exc:  # report a code only; messages could echo request details
        return f"ping: failed ({type(exc).__name__})"


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
        line = _ping(settings.api_key, settings.model, settings.timeout_seconds)
        print(line)
        return 0 if line.startswith("ping: ok") else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
