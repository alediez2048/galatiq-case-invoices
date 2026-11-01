# P5-10 — Accessibility, responsive layout, and browser test suite

Phase: 5 · Status: todo · Depends on: P5-06 – P5-09 · Requirements: P07, P12

## Context

[Mockup — behavior, accessibility, responsive layout](../mockup.md#screen-behavior-and-accessibility) and the [style guide checklist](../styleguide.md#implementation-checklist): keyboard reachability, focus return, text + icon statuses, right-aligned money with explicit currency, reduced motion, non-intrusive announcements, and four breakpoints (> 991, 768–991, 480–767, ≤ 479 px). Before calling the experience complete, inspect empty, loading, success, rejected, review, duplicate, and error states at desktop and narrow widths.

## Scope

- Add Playwright (proposed browser test tool) with tests running against a FastAPI instance on a temporary DB in offline mode.
- Keyboard: every control reachable; panels have headings and return focus to their trigger; visible focus outlines.
- Automated accessibility checks (e.g. axe) on each view; fix all serious/critical issues.
- Contrast verification for green-on-black text and the primary button against WCAG AA; record results.
- `prefers-reduced-motion` disables the wave mesh animation and transitions.
- Live regions announce run completion/failure once.
- Responsive layouts per breakpoint; on small screens outcome and primary reason appear before the source preview; line-item table scrolls horizontally without hiding columns permanently.
- Screenshot set for every state at 1280 px and 375 px, saved as test artifacts and compared by eye against `docs/mockups/index.html`.
- Routine navigation and refresh never trigger processing or payment (test reloads on processing and approval pages).

## Acceptance criteria

- [ ] Playwright suite passes, including the P5-09 browser tests.
- [ ] Zero serious/critical axe violations.
- [ ] Contrast results documented; any failures fixed or the token adjusted with a note in the style guide.
- [ ] Screenshot review completed for all listed states at both widths.
