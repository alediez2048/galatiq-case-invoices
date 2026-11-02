"""Per-run model session: call budget, tool-loop cap, tool box and call records."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from invoice_processing.codes import ModelErrorCode
from invoice_processing.reasoning.errors import ModelError


@dataclass(frozen=True)
class ModelCallRecord:
    """One attempt at one model step. Holds counts and timings, never prompt or output text."""

    step: str  # "recommend", "critique", "revise", "assist_extraction"
    attempt: int  # 1, or 2 for the single transport retry
    latency_ms: int
    input_tokens: int
    output_tokens: int
    tool_turns: int


class ToolSpecLike(Protocol):
    name: str
    description: str

    def json_schema(self) -> dict[str, Any]: ...


class ToolBox(Protocol):
    def specs(self, agent: str) -> Sequence[ToolSpecLike]: ...

    def call(self, agent: str, name: str, arguments_json: str) -> str: ...

    def reject(self, agent: str, name: str, reason: str) -> str: ...


class NullToolBox:
    """No tools for anyone: the offline simulator and bare sessions."""

    def specs(self, agent: str) -> list[ToolSpecLike]:
        return []

    def call(self, agent: str, name: str, arguments_json: str) -> str:
        return json.dumps({"error": "tool_rejected", "reason": "unknown_tool"})

    def reject(self, agent: str, name: str, reason: str) -> str:
        return json.dumps({"error": "tool_rejected", "reason": reason})


@dataclass
class ModelSession:
    budget: int
    used: int = 0  # top-level model steps charged so far, transport retries included
    tool_turn_cap: int = 3
    tools: ToolBox = field(default_factory=NullToolBox)
    calls: list[ModelCallRecord] = field(default_factory=list)

    def charge(self) -> None:
        """Reserve one step before sending it; refuse once the budget is spent."""
        if self.used >= self.budget:
            raise ModelError(
                ModelErrorCode.model_budget_exhausted,
                f"model call budget of {self.budget} step(s) is exhausted",
            )
        self.used += 1

    @classmethod
    def for_provider(cls, provider: object) -> "ModelSession":
        """A fresh session: live providers carry `settings`; the simulator gets budget 0."""
        settings = getattr(provider, "settings", None)
        if settings is None:
            return cls(budget=0)
        return cls(budget=settings.call_budget, tool_turn_cap=settings.tool_turn_cap)
