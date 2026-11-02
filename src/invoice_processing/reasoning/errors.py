"""Reasoning-layer exceptions and the classifier that turns SDK failures into stable codes.

`classify` never copies text from the original exception: SDK errors can echo request
metadata (including the bearer token), so messages are built only from the gRPC status
name or the exception's type name. Imports no SDK; grpc is only consulted when the live
path has already loaded it.
"""

import sys

from invoice_processing.codes import ModelErrorCode


class ProviderUnavailable(RuntimeError):
    """The requested reasoning provider cannot be used."""


TRANSIENT: frozenset[ModelErrorCode] = frozenset(
    {ModelErrorCode.model_timeout, ModelErrorCode.model_rate_limited}
)


class ModelError(Exception):
    """A live model step failed. Always recoverable: retry, or run offline separately."""

    recoverable = True

    def __init__(
        self, code: ModelErrorCode, message: str, *, transient: bool | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.transient = code in TRANSIENT if transient is None else transient

    def __repr__(self) -> str:
        return f"ModelError({self.code.value!r}, {self.message!r}, transient={self.transient})"


_GRPC_CODES: dict[str, ModelErrorCode] = {
    "DEADLINE_EXCEEDED": ModelErrorCode.model_timeout,
    "UNAVAILABLE": ModelErrorCode.model_unavailable,
    "INTERNAL": ModelErrorCode.model_unavailable,
    "UNKNOWN": ModelErrorCode.model_unavailable,
    "RESOURCE_EXHAUSTED": ModelErrorCode.model_rate_limited,
    "UNAUTHENTICATED": ModelErrorCode.model_auth_error,
    "PERMISSION_DENIED": ModelErrorCode.model_auth_error,
    "INVALID_ARGUMENT": ModelErrorCode.model_unavailable,
    "NOT_FOUND": ModelErrorCode.model_unavailable,
    "FAILED_PRECONDITION": ModelErrorCode.model_unavailable,
}
_TRANSIENT_GRPC = frozenset({"DEADLINE_EXCEEDED", "RESOURCE_EXHAUSTED", "UNAVAILABLE"})


def _grpc_status_name(exc: BaseException) -> str | None:
    """The gRPC status name of an `RpcError`, or None for any other exception."""
    grpc = sys.modules.get("grpc")
    if grpc is None or not isinstance(exc, grpc.RpcError):
        return None
    try:
        name = exc.code().name  # type: ignore[attr-defined]
    except Exception:
        return "UNKNOWN"
    return name if name in grpc.StatusCode.__members__ else "UNKNOWN"


def _mentions_api_key(exc: BaseException) -> bool:
    """True when the RPC details talk about the API key. Only matched, never echoed."""
    try:
        details = exc.details()  # type: ignore[attr-defined]
    except Exception:
        return False
    return isinstance(details, str) and "api key" in details.lower()


def classify(exc: BaseException) -> ModelError:
    if isinstance(exc, ModelError):
        return exc
    status = _grpc_status_name(exc)
    if status is not None:
        code = _GRPC_CODES.get(status, ModelErrorCode.model_unavailable)
        if status == "INVALID_ARGUMENT" and _mentions_api_key(exc):
            code = ModelErrorCode.model_auth_error  # xAI's answer to an incorrect key
        return ModelError(
            code,
            f"xAI request failed (gRPC {status})",
            transient=status in _TRANSIENT_GRPC,
        )
    if isinstance(exc, TimeoutError):
        return ModelError(ModelErrorCode.model_timeout, "xAI request timed out", transient=True)
    if isinstance(exc, ConnectionError):
        return ModelError(
            ModelErrorCode.model_unavailable, "xAI connection failed", transient=False
        )
    return ModelError(  # anything else, including a bug in the adapter: fail closed
        ModelErrorCode.model_unavailable,
        f"xAI request failed ({type(exc).__name__})",
        transient=False,
    )
