# P3-05 — Model-assisted extraction with one repair retry

Phase: 3 · Status: done · Depends on: P3-02, P3-03, P3-04, P2-08 · Requirements: A02, A07, P04

## Context

The ingestion agent may "repair malformed extraction once" ([system design](../systemsdesign.md#agent-responsibilities-and-tools)). Missing information is never invented, and model provenance must be recorded like rule provenance. Deterministic parsers already cover the supplied fixtures, so model assistance applies only to leftover extraction issues.

## Scope

- Trigger: after deterministic parsing and normalization, if extraction issues or `ambiguous_normalization` findings remain. No issues → no model call.
- `assist_extraction` input: the unresolved issues, the relevant source excerpts (delimited as untrusted data, P3-07), and the canonical item list. Output (Pydantic): proposed field values, each with a verbatim evidence quote and source location.
- Evidence check (deterministic): each proposal is accepted only if its quote appears at the stated location in the original source and the value is derivable from it (same digits/item tokens after documented rules). Otherwise discarded with `model_proposal_unsupported`.
- Deterministic values always win; a proposal that contradicts an existing parsed value → `model_parser_disagreement` → `needs_review`.
- Repair: if output fails schema validation, one retry with the validation error summary appended; a second failure leaves the issues unresolved (`needs_review`), not `failed`.
- Accepted proposals become `NormalizationEvent`s with provenance `model:<provider>/<model>`.
- Offline simulator returns "no proposals", so offline outcomes are unchanged.

## Acceptance criteria

- [ ] Fake provider proposing a vendor with a quote not present in the source → proposal discarded; vendor stays missing (INV-1009 variant).
- [ ] Fake provider proposing a value that matches its quote fills the field with model provenance.
- [ ] Malformed output then valid output → one repair, accepted; malformed twice → `needs_review`.
- [ ] Supplied fixtures in live mode trigger no extraction calls unless they have leftover issues (asserted via call counts with a fake).
