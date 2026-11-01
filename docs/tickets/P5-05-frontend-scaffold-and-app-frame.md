# P5-05 — Frontend scaffold, design tokens, and app frame

Phase: 5 · Status: todo · Depends on: P5-01 · Requirements: P12

## Context

The approved HTML mockup (`docs/mockups/index.html`) is the visual baseline; React owns presentation and must not duplicate policy. Runtime assets stay local for offline use ([techstack — local UI](../techstack.md#local-ui)). Visual tokens come from the [style guide](../styleguide.md).

## Scope

- `frontend/`: Vite + React + TypeScript (strict), npm with a committed `package-lock.json`.
- Typed API client generated from the exported OpenAPI schema (e.g. `openapi-typescript`), plus a thin fetch wrapper that sends idempotency keys and maps the `{code, message}` error body.
- Design tokens as CSS custom properties: `#000000` / `#070707` backgrounds, `#FFFFFF` / `#CFCFCF` / `rgba(255,255,255,0.6)` text, `#202020` grid lines, `#009A6C` accent, pill and card fills, type scale, radii, spacing, `0.2s ease` transitions. Font stack `Aventa, Arial, sans-serif` with no bundled Aventa file unless licensed.
- App frame from the mockup: header wordmark `GALATIQ / Invoice Operations`, persistent mode badge, Setup button; nav Overview / Invoices / Needs review; footer "Case-study prototype · Local workspace · All payments are simulated".
- Routing for the three views, invoice detail, and a setup/readiness panel.
- Status component: text + distinct icon per outcome; color never the only signal.
- Vite dev proxy to the FastAPI port; production build served as static files by FastAPI (optional) or documented separately.

## Acceptance criteria

- [ ] `npm ci && npm run typecheck && npm run build` pass from a clean clone.
- [ ] No runtime request to any external origin (fonts, CDNs, analytics); checked in the built bundle.
- [ ] Frame matches the mockup header, nav, and footer at desktop width (screenshot comparison noted in the PR).
- [ ] Mode badge reflects the selected workspace mode and is visible on every view.
