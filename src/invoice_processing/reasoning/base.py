"""Reasoning provider seam: the offline simulator and the live xAI provider implement it.

Every method takes the run's `ModelSession` last; live providers charge it per step.
Nothing a provider returns can authorize payment: the deterministic gate decides.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import NoReturn, Protocol

from invoice_processing.codes import ExecutionMode
from invoice_processing.reasoning.session import ModelSession
from invoice_processing.schemas import (
    ApprovalRecommendation,
    Critique,
    ExtractionAssistRequest,
    ExtractionProposals,
    NormalizedInvoice,
    ValidationFinding,
)


@dataclass(frozen=True)
class PolicyContext:
    policy_version: str
    high_value_threshold: Decimal


class ReasoningProvider(Protocol):
    mode: ExecutionMode
    provider: str
    model: str
    prompt_version: str | None
    extract_prompt_version: str | None  # the extraction-assist prompt; None offline
    excerpt_chars: int  # max source characters sent per assist request; 0 offline

    def recommend(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        policy: PolicyContext,
        session: ModelSession,
    ) -> ApprovalRecommendation: ...

    def critique(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        recommendation: ApprovalRecommendation,
        policy: PolicyContext,
        session: ModelSession,
    ) -> Critique: ...

    def revise(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        recommendation: ApprovalRecommendation,
        critique: Critique,
        policy: PolicyContext,
        session: ModelSession,
    ) -> ApprovalRecommendation: ...

    def assist_extraction(
        self, request: ExtractionAssistRequest, session: ModelSession
    ) -> ExtractionProposals: ...


_NO_MODEL_CALLS = "human-review runs make no model calls"


class NoModelProvider:
    """The provider of a human-review run (Decision 13): it carries the run's mode and makes
    no model call. Any call is a bug, so every method raises."""

    provider = "none"
    model = "none"
    prompt_version: str | None = None
    extract_prompt_version: str | None = None
    excerpt_chars = 0

    def __init__(self, mode: ExecutionMode) -> None:
        self.mode = mode

    def recommend(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        policy: PolicyContext,
        session: ModelSession,
    ) -> NoReturn:
        raise AssertionError(_NO_MODEL_CALLS)

    def critique(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        recommendation: ApprovalRecommendation,
        policy: PolicyContext,
        session: ModelSession,
    ) -> NoReturn:
        raise AssertionError(_NO_MODEL_CALLS)

    def revise(
        self,
        invoice: NormalizedInvoice,
        findings: list[ValidationFinding],
        recommendation: ApprovalRecommendation,
        critique: Critique,
        policy: PolicyContext,
        session: ModelSession,
    ) -> NoReturn:
        raise AssertionError(_NO_MODEL_CALLS)

    def assist_extraction(
        self, request: ExtractionAssistRequest, session: ModelSession
    ) -> NoReturn:
        raise AssertionError(_NO_MODEL_CALLS)
