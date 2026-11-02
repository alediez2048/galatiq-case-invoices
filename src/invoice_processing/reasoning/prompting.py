"""Versioned prompt files and the delimited, escaped data block that carries invoice data.

Invoice content is untrusted: it reaches the model only inside one `data_block`, whose
delimiters cannot be forged from within (any occurrence in the text is escaped first), and
every prompt states that the block's content is never an instruction. The payload carries
normalized fields and finding codes only, never raw source text or evidence snippets.
"""

import json
import re
from collections.abc import Mapping
from functools import cache
from importlib.resources import files
from typing import Any

from invoice_processing.reasoning.base import PolicyContext
from invoice_processing.schemas import NormalizedInvoice, ValidationFinding

OPEN = "<<<INVOICE_DATA"
CLOSE = "INVOICE_DATA>>>"
PROMPT_REVISION = "v1"

_NAME = re.compile(r"[a-z][a-z_]*")
# Case-insensitive so a near-miss ("<<<invoice_data") cannot pass for a delimiter either.
# The underscore becomes a hyphen: the result stays valid inside a JSON string and contains
# neither delimiter, so one pass is enough.
_ESCAPES = (
    (re.compile(re.escape(OPEN), re.I), "<<<INVOICE-DATA"),
    (re.compile(re.escape(CLOSE), re.I), "INVOICE-DATA>>>"),
)
_FINDING_FIELDS = {"code", "severity", "field", "item", "expected", "observed"}
NOTES_MAX_CHARS = 1000
_TRUNCATED = " [truncated]"


@cache
def load_prompt(name: str) -> tuple[str, str]:
    """The prompt text for `name` and its version, e.g. ("...", "recommend.v1")."""
    version = f"{name}.{PROMPT_REVISION}"
    resource = files("invoice_processing.reasoning") / "prompts" / f"{version}.md"
    if not _NAME.fullmatch(name) or not resource.is_file():
        raise ValueError(f"unknown prompt: {name!r}")
    return resource.read_text(encoding="utf-8"), version


def data_block(text: str) -> str:
    """Wrap untrusted text in the data delimiters after escaping any delimiter inside it."""
    for pattern, replacement in _ESCAPES:
        text = pattern.sub(replacement, text)
    return f"{OPEN}\n{text}\n{CLOSE}"


def invoice_payload(
    invoice: NormalizedInvoice,
    findings: list[ValidationFinding],
    policy: PolicyContext,
    *,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """JSON of the normalized invoice, finding codes and the policy summary (no raw source)."""
    fields = invoice.model_dump(
        mode="json",
        exclude={"normalization_events": True, "lines": {"__all__": {"evidence"}}},
    )
    notes = fields.get("notes")
    if notes is not None and len(notes) > NOTES_MAX_CHARS:  # untrusted free text: keep it short
        fields["notes"] = notes[:NOTES_MAX_CHARS] + _TRUNCATED
    data: dict[str, Any] = {
        "invoice": fields,
        "findings": [f.model_dump(mode="json", include=_FINDING_FIELDS) for f in findings],
        "policy": {
            "policy_version": policy.policy_version,
            "high_value_threshold": str(policy.high_value_threshold),
        },
        **(extra or {}),
    }
    return json.dumps(data, sort_keys=True)
