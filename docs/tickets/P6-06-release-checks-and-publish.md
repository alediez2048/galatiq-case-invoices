# P6-06 — Release checks and public GitHub submission

Phase: 6 · Status: todo · Depends on: P6-01 – P6-05 · Requirements: A10

## Context

Submission is a link to a public github.com repository. Commit synthetic fixtures and code; exclude keys, local ledgers, uploads, environment files, and any real financial documents ([constraints — dataset limitations](../contraints.md#dataset-and-business-limitations)). The working fork is `alediez2048/galatiq-case-invoices`; `origin` points there and `upstream` points to `galatiq-ai`. Nothing should be pushed or opened against upstream.

## Scope

- Secret and artifact scan over the full git history (e.g. `gitleaks` or equivalent): no keys, `.env`, `*.db`, `uploads/`, `output/`.
- Clean-clone check in a new directory: install from locks, seed, `pytest`, `ruff`, `npm ci`, typecheck, build, Playwright, CLI on 1001, and the live smoke test when credentials are available.
- Record Python, Node, and OS versions used for final verification in `docs/development.md`.
- Optional GitHub Actions workflow running offline checks only (no secrets, no live tests).
- Push to the fork's default branch with user confirmation; verify the public URL renders README, docs, and links while logged out.
- Optional tag `v1.0.0` with a short release note.

## Acceptance criteria

- [ ] Secret/artifact scan clean.
- [ ] Clean-clone check passes; results noted with date.
- [ ] Public repository URL confirmed reachable while logged out.
- [ ] No push, issue, or PR made to the upstream `galatiq-ai` repository.
