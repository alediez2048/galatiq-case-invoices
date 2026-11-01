# P6-02 — Audit trail completeness and export

Phase: 6 · Status: todo · Depends on: P4-07, P5-03 · Requirements: P08

## Context

P08: persist source hash, run identity, evidence, tool outcomes, normalization, checks, critique summary, policy version, mode, and payment result. Never log credentials or private model reasoning.

## Scope

- Test that, for every run in the P6-01 corpus campaign, each P08 item is present and linked to the run and version.
- Test that no audit payload, log line, or API response contains a sentinel secret or prompt text.
- `python -m invoice_processing.audit export INVOICE_ID` → one JSON document with the invoice's full history (sources, versions, runs, findings, decisions, tool calls, corrections, human reviews, payment, ordered events).
- Short `docs/audit.md` explaining what is recorded, where, and what is deliberately not recorded.

## Acceptance criteria

- [ ] Completeness test passes for all corpus runs, offline and scripted-live.
- [ ] Export for INV-1004 (base + revised) shows both versions, both runs, the single payment, and the blocking reason for the revision.
- [ ] Secret-sentinel test passes across logs, DB, and API.
