import grpc
import pytest

from invoice_processing.codes import ModelErrorCode as E
from invoice_processing.reasoning.errors import TRANSIENT, ModelError, classify
from tests.fakes.xai_client import FakeRpcError

SENTINEL = "sk-SENTINEL-123"


def test_model_error_codes_are_stable():
    assert {c.value for c in E} == {
        "model_auth_error",
        "model_rate_limited",
        "model_timeout",
        "model_unavailable",
        "model_output_invalid",
        "model_refused",
        "model_budget_exhausted",
        "model_tool_loop_exceeded",
    }
    assert TRANSIENT == {E.model_timeout, E.model_rate_limited}


@pytest.mark.parametrize(
    ("status", "code", "transient"),
    [
        (grpc.StatusCode.DEADLINE_EXCEEDED, E.model_timeout, True),
        (grpc.StatusCode.UNAVAILABLE, E.model_unavailable, True),
        (grpc.StatusCode.INTERNAL, E.model_unavailable, False),
        (grpc.StatusCode.UNKNOWN, E.model_unavailable, False),
        (grpc.StatusCode.RESOURCE_EXHAUSTED, E.model_rate_limited, True),
        (grpc.StatusCode.UNAUTHENTICATED, E.model_auth_error, False),
        (grpc.StatusCode.PERMISSION_DENIED, E.model_auth_error, False),
        (grpc.StatusCode.INVALID_ARGUMENT, E.model_unavailable, False),
        (grpc.StatusCode.NOT_FOUND, E.model_unavailable, False),
        (grpc.StatusCode.FAILED_PRECONDITION, E.model_unavailable, False),
        (grpc.StatusCode.CANCELLED, E.model_unavailable, False),
    ],
)
def test_grpc_status_mapping(status, code, transient):
    err = classify(FakeRpcError(status, "details"))
    assert isinstance(err, ModelError)
    assert err.code is code and err.transient is transient and err.recoverable is True
    assert status.name in err.message


@pytest.mark.parametrize(
    ("exc", "code", "transient"),
    [
        (TimeoutError("slow"), E.model_timeout, True),
        (ConnectionError("reset"), E.model_unavailable, False),
        (ValueError("weird"), E.model_unavailable, False),
    ],
)
def test_python_exception_mapping(exc, code, transient):
    err = classify(exc)
    assert err.code is code and err.transient is transient


def test_model_error_passes_through_unchanged():
    original = ModelError(E.model_refused, "refused")
    assert classify(original) is original
    assert original.transient is False
    assert ModelError(E.model_timeout, "t").transient is True


def test_rpc_error_with_broken_code_is_unavailable():
    class Broken(grpc.RpcError):
        def code(self):
            raise RuntimeError(SENTINEL)

    err = classify(Broken())
    assert err.code is E.model_unavailable and SENTINEL not in str(err)


def test_sdk_details_with_api_key_never_reach_the_message():
    leaky = [
        FakeRpcError(grpc.StatusCode.UNAUTHENTICATED, f"bad key Bearer {SENTINEL}"),
        TimeoutError(f"timeout calling with {SENTINEL}"),
        RuntimeError(f"authorization: Bearer {SENTINEL}"),
    ]
    for exc in leaky:
        err = classify(exc)
        for rendered in (str(err), repr(err), err.message, str(err.args)):
            assert SENTINEL not in rendered
            assert "Bearer" not in rendered
        assert err.__cause__ is None and err.__context__ is None
