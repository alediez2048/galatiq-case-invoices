"""Scripted stand-in for `xai_sdk.Client`, mirroring only the subset `XaiProvider` uses.

    client = FakeXaiClient([ToolCalls([("lookup_inventory", {"items": ["WidgetA"]})]),
                            Parsed({...})])
    provider = XaiProvider(settings, lambda s: client)

Mirrored surface: `client.chat.create(model, *, messages, tools, **kw) -> FakeChat`;
`FakeChat.append(message_or_response)`, `.sample() -> FakeResponse`,
`.parse(shape) -> (FakeResponse, shape)`; responses expose `content`, `finish_reason`,
`tool_calls` (each with `.id`, `.function.name`, `.function.arguments` as a JSON string),
`usage.prompt_tokens` / `usage.completion_tokens`, `reasoning_content`, `id`.

Step semantics (one step is consumed per network round trip):
- `Raise(code_or_exc)` is consumed by whichever call meets it (`sample` or `parse`); a
  `grpc.StatusCode` raises a `grpc.RpcError` whose `.code()` returns it.
- `ToolCalls([...])` is consumed by `sample()` and returns those tool calls. If `parse()`
  meets it, the real SDK would validate empty content and raise, so the fake does too.
- `Parsed(obj)` / `Malformed(text)` are consumed by `parse()`. A `sample()` that meets one
  returns a plain final answer (no tool calls) without consuming it, i.e. the model
  stopped calling tools. `Parsed(dict)` is validated with `shape.model_validate_json` exactly
  like the SDK; `Parsed(BaseModel)` is returned as-is (an unvalidated object, to exercise the
  adapter's local re-validation). `Malformed(text)` raises the SDK's pydantic error;
  `Malformed("")` is an empty (refused) answer.

Every `sample`/`parse` call appends a `FakeRequest` to `client.requests`.
"""

import itertools
import json
from dataclasses import dataclass, field
from typing import Any

import grpc
from pydantic import BaseModel


@dataclass(frozen=True)
class Parsed:
    obj: dict[str, Any] | BaseModel


@dataclass(frozen=True)
class ToolCalls:
    calls: list[tuple[str, dict[str, Any]]]


@dataclass(frozen=True)
class Malformed:
    text: str


@dataclass(frozen=True)
class Raise:
    error: grpc.StatusCode | BaseException
    details: str = "scripted failure"


Step = Parsed | ToolCalls | Malformed | Raise


class ScriptExhausted(AssertionError):
    """The adapter made more requests than the script provides."""


class FakeRpcError(grpc.RpcError):
    """Shaped like grpc's `_InactiveRpcError`: `.code()`, `.details()` and a noisy str()."""

    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        super().__init__(f"<RpcError status={code} details={details!r}>")
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:
        return self._code

    def details(self) -> str:
        return self._details


@dataclass(frozen=True)
class FakeFunction:
    name: str
    arguments: str


@dataclass(frozen=True)
class FakeToolCall:
    id: str
    function: FakeFunction


@dataclass(frozen=True)
class FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class FakeResponse:
    id: str
    content: str = ""
    finish_reason: str = "REASON_STOP"
    tool_calls: list[FakeToolCall] = field(default_factory=list)
    usage: FakeUsage = field(default_factory=FakeUsage)
    reasoning_content: str = "HIDDEN-REASONING-NEVER-PERSIST"


@dataclass(frozen=True)
class FakeRequest:
    kind: str  # "sample" or "parse"
    model: str
    tool_names: list[str]
    roles: list[str]
    content_length: int
    text: str  # every message's text joined; for leak assertions only


@dataclass
class _Message:
    role: str
    text: str


def _role_of(message: Any) -> str:
    """Role of an `xai_sdk.chat` proto message (`ROLE_USER` -> "user")."""
    enum = message.DESCRIPTOR.fields_by_name["role"].enum_type
    return enum.values_by_number[message.role].name.removeprefix("ROLE_").lower()


def _text_of(message: Any) -> str:
    return "".join(part.text for part in message.content)


def _tool_name(tool: Any) -> str:
    return tool.function.name


class FakeChat:
    def __init__(self, client: "FakeXaiClient", model: str, messages: list, tools: list) -> None:
        self._client = client
        self.model = model
        self.tool_names = [_tool_name(t) for t in tools]
        self.messages: list[_Message] = [_Message(_role_of(m), _text_of(m)) for m in messages]
        self.response_format: type[BaseModel] | None = None

    def append(self, message: Any) -> "FakeChat":
        if isinstance(message, FakeResponse):
            calls = json.dumps(
                [[c.function.name, c.function.arguments] for c in message.tool_calls]
            )
            self.messages.append(_Message("assistant", message.content + calls))
        else:
            self.messages.append(_Message(_role_of(message), _text_of(message)))
        return self

    def _record(self, kind: str) -> None:
        text = "\n".join(m.text for m in self.messages)
        self._client.requests.append(
            FakeRequest(
                kind=kind,
                model=self.model,
                tool_names=list(self.tool_names),
                roles=[m.role for m in self.messages],
                content_length=len(text),
                text=text,
            )
        )

    def sample(self) -> FakeResponse:
        self._record("sample")
        step = self._client._peek()
        if isinstance(step, Raise):
            self._client._pop()
            _raise(step)
        if isinstance(step, ToolCalls):
            self._client._pop()
            return self._client._response(
                finish_reason="REASON_TOOL_CALLS",
                tool_calls=[self._client._tool_call(name, args) for name, args in step.calls],
            )
        return self._client._response(content="final answer follows")

    def parse(self, shape: type[BaseModel]) -> tuple[FakeResponse, BaseModel]:
        self.response_format = shape
        self._record("parse")
        step = self._client._pop()
        if isinstance(step, Raise):
            _raise(step)
        if isinstance(step, ToolCalls | Malformed):
            # A tool-call-only answer has empty content; the SDK validates it and raises.
            text = step.text if isinstance(step, Malformed) else ""
            parsed = shape.model_validate_json(text)  # raises like the SDK for invalid JSON
            return self._client._response(content=text), parsed
        assert isinstance(step, Parsed)
        if isinstance(step.obj, BaseModel):
            content = step.obj.model_dump_json(warnings=False)
            return self._client._response(content=content), step.obj
        content = json.dumps(step.obj)
        return self._client._response(content=content), shape.model_validate_json(content)


def _raise(step: Raise) -> None:
    if isinstance(step.error, grpc.StatusCode):
        raise FakeRpcError(step.error, step.details)
    raise step.error


class _FakeChatClient:
    def __init__(self, client: "FakeXaiClient") -> None:
        self._client = client

    def create(
        self, model: str, *, messages: list | None = None, tools: list | None = None, **_: Any
    ) -> FakeChat:
        chat = FakeChat(self._client, model, list(messages or []), list(tools or []))
        self._client.chats.append(chat)
        return chat


class FakeXaiClient:
    def __init__(self, script: list[Step], *, prompt_tokens: int = 11, completion_tokens: int = 7):
        self.script: list[Step] = list(script)
        self.requests: list[FakeRequest] = []
        self.chats: list[FakeChat] = []
        self.chat = _FakeChatClient(self)
        self._usage = FakeUsage(prompt_tokens, completion_tokens)
        self._ids = itertools.count(1)

    def _peek(self) -> Step:
        if not self.script:
            raise ScriptExhausted(f"script exhausted after {len(self.requests)} request(s)")
        return self.script[0]

    def _pop(self) -> Step:
        step = self._peek()
        self.script.pop(0)
        return step

    def _response(self, **kwargs: Any) -> FakeResponse:
        return FakeResponse(id=f"resp-{next(self._ids)}", usage=self._usage, **kwargs)

    def _tool_call(self, name: str, args: dict[str, Any]) -> FakeToolCall:
        return FakeToolCall(
            id=f"call-{next(self._ids)}", function=FakeFunction(name, json.dumps(args))
        )

    @property
    def remaining(self) -> int:
        return len(self.script)

    def close(self) -> None:
        pass


def factory(client: FakeXaiClient):
    """`client_factory` for `XaiProvider` that always hands back `client`."""
    return lambda settings: client
