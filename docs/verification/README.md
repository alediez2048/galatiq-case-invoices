# Verification records

| Record | What it covers |
| --- | --- |
| [robustness-2026-11-01.md](robustness-2026-11-01.md) | Offline robustness campaign |
| `live-<date>.md` | Real-Grok smoke run (P3-10): pending the user's xAI key |

Live records are written by `tests/live/test_live_smoke.py` (`RUN_LIVE_TESTS=1 uv run pytest -m live`, see [development](../development.md)). Each holds the exact model id, xai-sdk version, per-invoice status, model calls, latency, tool calls, token usage, a cost estimate and any divergence from the expected outcome. Keys, prompts and model reasoning are never written.
