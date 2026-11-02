"""Live reasoning on Grok through the official `xai_sdk` (gRPC). Loaded only in live mode.

Each provider method is one top-level *step*: charge the session, open a chat, run the
bounded tool loop when the agent has tools, then ask for structured output with
`chat.parse` and re-validate it locally. Transport failures are classified into stable
`ModelErrorCode`s; a transient one is retried once as a new, separately charged attempt.

Only this subset of the SDK is used (and mirrored by `tests/fakes/xai_client.py`):
`Client(api_key, timeout, channel_options)`, `client.chat.create(model, messages, tools)`,
`chat.append`, `chat.sample`, `chat.parse`, `response.tool_calls[*].id / .function.name / .function.arguments`,
`response.usage.prompt_tokens / .completion_tokens`, and the `xai_sdk.chat` message builders
`system`, `user`, `tool`, `tool_result`. `reasoning_content` is never read.

Bounds (P3-04). The session budget (`MODEL_CALL_BUDGET`, default 6) counts top-level steps
and transport retries; tool follow-up turns do not count. A step with tools makes at most
`tool_turn_cap + 2` requests (the first sample, one sample per tool turn, then the parse);
a step without tools makes one. At most `MAX_TOOL_CALLS_PER_TURN` (8) tool calls run per
turn; the rest of that turn's calls are answered `tool_rejected` without running. Worst case per invoice: `budget * (tool_turn_cap + 2)`
requests (6 * 5 = 30 with the defaults). Normal call plan: extraction assist 0-2 (only when
needed; one repair), recommendation 1, critique 1, revision 0-1, so at most 5 steps plus
transport retries within the budget of 6.
"""

import importlib.metadata
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from invoice_processing.codes import ExecutionMode, ModelErrorCode
from invoice_processing.reasoning.base import PolicyContext
from invoice_processing.reasoning.errors import ModelError, classify
from invoice_processing.reasoning.prompting import data_block, invoice_payload, load_prompt
from invoice_processing.reasoning.session import ModelCallRecord, ModelSession
from invoice_processing.schemas import (
    ApprovalRecommendation,
    Critique,
    CritiqueOutput,
    ExtractionAssistRequest,
    ExtractionProposals,
    NormalizedInvoice,
    RecommendationOutput,
    ValidationFinding,
)
from invoice_processing.settings import LiveSettings

ClientFactory = Callable[[LiveSettings], Any]

_APPROVAL_STEPS = ("recommend", "critique", "revise")
# The recorded prompt version names every approval prompt file the run may use.
PROMPT_VERSION = ",".join(load_prompt(step)[1] for step in _APPROVAL_STEPS)

_ASSIST_STEP, _ASSIST_PROMPT = "assist_extraction", "extract"
# Recorded on the ingestion agent's model-call events (the decision records PROMPT_VERSION).
EXTRACT_PROMPT_VERSION = load_prompt(_ASSIST_PROMPT)[1]
_APPROVAL, _INGESTION = "approval", "ingestion"

# Tool calls dispatched per model turn; the rest of that turn's calls are answered with a
# rejection and never run.
MAX_TOOL_CALLS_PER_TURN = 8
_TOO_MANY_TOOL_CALLS = json.dumps({"error": "tool_rejected", "reason": "too_many_tool_calls"})


def _system_prompt(step: str) -> str:
    return load_prompt(_ASSIST_PROMPT if step == _ASSIST_STEP else step)[0]


# The SDK's default channel turns on gRPC's own retries (up to 5 attempts on UNAVAILABLE
# inside one call), which would break the bound of 2 transport attempts per step.
_CHANNEL_OPTIONS = [("grpc.enable_retries", 0)]


def real_client_factory(settings: LiveSettings) -> Any:
    """Build the official SDK client. Construction is lazy: no RPC until the first call.

    The SDK's OpenTelemetry tracer is created when its modules are imported and would see
    request content, so it is switched off first unless the environment says otherwise.
    """
    os.environ.setdefault("XAI_SDK_DISABLE_TRACING", "1")
    import xai_sdk

    return xai_sdk.Client(
        api_key=settings.api_key,
        timeout=settings.timeout_seconds,
        channel_options=list(_CHANNEL_OPTIONS),
    )


def _sdk_version() -> str | None:
    try:
        return importlib.metadata.version("xai-sdk")
    except importlib.metadata.PackageNotFoundError:
        return None


def _recommendation_data(rec: ApprovalRecommendation) -> dict:
    return rec.model_dump(mode="json", include=set(RecommendationOutput.model_fields))


@dataclass
class _Attempt:
    input_tokens: int = 0
    output_tokens: int = 0
    tool_turns: int = 0

    def add_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        self.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        self.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)


def _output_error(exc: ValidationError, *, tools_offered: bool = False) -> ModelError:
    """Map a structured-output validation failure; never echoes the model's text.

    `chat.parse` validates inside the SDK, so an empty answer cannot be inspected further.
    With tools offered, an empty final answer is (almost always) a tool call where the
    final answer was due, so it counts as a runaway tool loop; without tools it is a refusal.
    """
    errors = exc.errors(include_url=False, include_context=False, include_input=True)
    empty = (
        len(errors) == 1
        and errors[0]["type"] == "json_invalid"
        and not str(errors[0].get("input", "")).strip()
    )
    if empty and tools_offered:
        return ModelError(
            ModelErrorCode.model_tool_loop_exceeded, "model called tools instead of answering"
        )
    if empty:
        return ModelError(ModelErrorCode.model_refused, "model returned an empty answer")
    return ModelError(
        ModelErrorCode.model_output_invalid,
        f"model output failed schema validation ({len(errors)} error(s))",
    )


class XaiProvider:
    mode = ExecutionMode.live
    provider = "xai"
    prompt_version = PROMPT_VERSION
    extract_prompt_version = EXTRACT_PROMPT_VERSION

    def __init__(self, settings: LiveSettings, client_factory: ClientFactory) -> None:
        self.settings = settings
        self.model = settings.model
        self.excerpt_chars = settings.excerpt_chars
        self.sdk_version = _sdk_version()
        self._client_factory = client_factory
        self._client: Any = None

    def __repr__(self) -> str:
        return f"XaiProvider(model={self.model!r}, sdk_version={self.sdk_version!r})"

    # --- provider methods ---------------------------------------------------------------

    def recommend(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        policy: PolicyContext,
        session: ModelSession,
    ) -> ApprovalRecommendation:
        payload = invoice_payload(invoice, findings, policy)
        out = self._step("recommend", _APPROVAL, payload, RecommendationOutput, session)
        return ApprovalRecommendation(**out.model_dump(), **self._provenance())

    def critique(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        recommendation: ApprovalRecommendation,
        policy: PolicyContext,
        session: ModelSession,
    ) -> Critique:
        extra = {"recommendation": _recommendation_data(recommendation)}
        payload = invoice_payload(invoice, findings, policy, extra=extra)
        out = self._step("critique", _APPROVAL, payload, CritiqueOutput, session)
        return Critique(**out.model_dump(), **self._provenance())

    def revise(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        recommendation: ApprovalRecommendation,
        critique: Critique,
        policy: PolicyContext,
        session: ModelSession,
    ) -> ApprovalRecommendation:
        extra = {
            "recommendation": _recommendation_data(recommendation),
            "critique": critique.model_dump(mode="json", include=set(CritiqueOutput.model_fields)),
        }
        payload = invoice_payload(invoice, findings, policy, extra=extra)
        out = self._step("revise", _APPROVAL, payload, RecommendationOutput, session)
        return ApprovalRecommendation(**out.model_dump(), **self._provenance())

    def assist_extraction(
        self, request: ExtractionAssistRequest, session: ModelSession
    ) -> ExtractionProposals:
        # Excerpts are untrusted source text: they travel only inside the step's data block.
        payload = json.dumps(request.model_dump(mode="json"), sort_keys=True)
        return self._step(_ASSIST_STEP, _INGESTION, payload, ExtractionProposals, session)

    # --- one step -----------------------------------------------------------------------

    def _provenance(self) -> dict[str, Any]:
        return {"mode": self.mode, "provider": self.provider, "model": self.model}

    def _step[T: BaseModel](
        self, step: str, agent: str, payload: str, output: type[T], session: ModelSession
    ) -> T:
        """One top-level step; `payload` is untrusted data and is sent only in a data block."""
        for attempt in (1, 2):
            session.charge()  # raises model_budget_exhausted before anything is sent
            stats = _Attempt()
            started = time.monotonic()
            error: ModelError | None = None
            try:
                result = self._attempt(step, agent, payload, output, session, stats)
            except Exception as exc:  # classified below; the SDK text is never kept
                error = classify(exc)
            session.calls.append(
                ModelCallRecord(
                    step=step,
                    attempt=attempt,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    input_tokens=stats.input_tokens,
                    output_tokens=stats.output_tokens,
                    tool_turns=stats.tool_turns,
                )
            )
            if error is None:
                return result
            if not (error.transient and attempt == 1):
                break
        # Raised outside the `except` block so neither __cause__ nor __context__ links back
        # to an SDK exception whose text could carry request metadata.
        assert error is not None
        raise error

    def _attempt[T: BaseModel](
        self,
        step: str,
        agent: str,
        payload: str,
        output: type[T],
        session: ModelSession,
        stats: _Attempt,
    ) -> T:
        from xai_sdk.chat import system, tool, tool_result, user

        if self._client is None:
            self._client = self._client_factory(self.settings)
        specs = list(session.tools.specs(agent))
        chat = self._client.chat.create(
            model=self.model,
            messages=[system(_system_prompt(step)), user(data_block(payload))],
            tools=[tool(s.name, s.description, s.json_schema()) for s in specs],
        )
        if specs:
            response = chat.sample()
            stats.add_usage(response)
            while response.tool_calls:
                if stats.tool_turns >= session.tool_turn_cap:
                    raise ModelError(
                        ModelErrorCode.model_tool_loop_exceeded,
                        f"model still calling tools after {session.tool_turn_cap} turn(s)",
                    )
                chat.append(response)
                for index, call in enumerate(response.tool_calls):
                    if index < MAX_TOOL_CALLS_PER_TURN:
                        result = session.tools.call(
                            agent, call.function.name, call.function.arguments
                        )
                    else:  # every call id still gets an answer, but nothing runs
                        result = _TOO_MANY_TOOL_CALLS
                    # Tool results can quote invoice text: they travel as data, like the payload.
                    chat.append(tool_result(data_block(result), tool_call_id=call.id))
                stats.tool_turns += 1
                response = chat.sample()
                stats.add_usage(response)
        return self._parse(chat, output, stats, tools_offered=bool(specs))

    @staticmethod
    def _parse[T: BaseModel](
        chat: Any, output: type[T], stats: _Attempt, *, tools_offered: bool
    ) -> T:
        try:
            response, parsed = chat.parse(output)
        except ValidationError as exc:  # the SDK validates the JSON against `output`
            error = _output_error(exc, tools_offered=tools_offered)
        else:
            stats.add_usage(response)
            if not isinstance(parsed, BaseModel):
                error = ModelError(
                    ModelErrorCode.model_output_invalid, "model output is not an object"
                )
            else:
                # Re-validate locally: never trust that the SDK (or a fake) checked the shape.
                try:
                    return output.model_validate(parsed.model_dump(warnings=False))
                except ValidationError as exc:
                    error = _output_error(exc)
        raise error  # outside `except`: no chained exception carries the model's text
