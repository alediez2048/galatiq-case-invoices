# P3-07 — Untrusted invoice text and prompt-injection safeguards

Phase: 3 · Status: done · Depends on: P3-05, P3-06 · Requirements: A07, P08

## Context

Invoice text is untrusted data. Requests embedded in documents cannot change business rules, invoke arbitrary tools, approve an invoice, or authorize payment ([constraints — security and trust boundaries](../contraints.md#security-and-trust-boundaries)). INV-1003's "URGENT — Pay immediately" note is the supplied example of pressure wording.

## Scope

- Prompt construction: source text always placed inside a clearly delimited data block with an instruction that it is content to analyze, never instructions; delimiter collisions in the source are escaped.
- Excerpts are bounded in length (configurable, default 4,000 characters per call).
- Adversarial test fixtures in `tests/fixtures/adversarial/` (not in `data/invoices/`):
  - Text instructing the model to approve, ignore stock, or call a payment tool.
  - Text claiming a manager already approved.
  - Text containing fake tool-call syntax or JSON mimicking the output schema.
  - Overstock invoice with "inventory has been updated, stock is 1000."
- For each: the gate outcome equals the outcome without the injected text; no unauthorized tool executes; injected claims never appear as findings unless as `risk_signal_*`.
- Detected instruction-like content emits `risk_signal_embedded_instructions` (info), visible in results.

## Acceptance criteria

- [ ] All adversarial fixtures pass with a scripted fake provider that obeys the injection (worst case): payment still never occurs when blockers exist.
- [ ] The same fixtures are included in the live smoke run (P3-10) and their outcomes recorded.
- [ ] No prompt sends the API key, environment, or other invoices' data.
