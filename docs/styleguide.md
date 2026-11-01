# GALATIQ STYLE GUIDE

Status: visual reference for the invoice-processing project, based on the user-provided site observations. These observations have not been independently verified against the live site. Unconfirmed usage and inferred behavior are called out below.

Related: [system design](systemsdesign.md), [technology stack](techstack.md).

## Look and feel

Dark and technical: pure black backgrounds, white typography, and one green accent. A green wave mesh is the main hero visual, with thin grid lines framing the content.

The reference site is reported to use Webflow. This describes the reference site, not a requirement to change the project's approved React + TypeScript frontend and FastAPI backend.

## Colors

| Token or role | Value | Usage / qualification |
| --- | --- | --- |
| Page background | `#000000` | Primary black background. |
| Alternate background | `#070707` | Alternate black surface. |
| Primary text | `#FFFFFF` | Headings and primary text. |
| Intro text | `#CFCFCF` | Introductory paragraphs. |
| Muted text | `rgba(255, 255, 255, 0.6)` | Job titles, stat labels, and footer links. |
| Grid border | `#202020` | Thin grid lines framing content. |
| Accent | `#009A6C` | Green accent and stat numbers. |
| Dark grey | `#575757` | Defined in the reference; actual usage unconfirmed. |
| Pill fill | `rgba(23, 145, 106, 0.13)` | Translucent green pill background. |
| Card fill | `rgba(255, 255, 255, 0.1)` | Translucent white card surface. |
| Card border | `rgba(255, 255, 255, 0.1)` | Translucent white card outline. |

Apply opacity to the specified color, not the entire component, so text remains independently legible.

## Gradients and glow

These values were supplied as reference definitions. Their element assignments are unconfirmed; do not treat them as verified hero, card, or button treatments.

| Treatment | Values | Unknowns |
| --- | --- | --- |
| Fade | Transparent → `rgb(18, 59, 41)` | Direction, stops, and target element. |
| Radial gradient | `rgba(23, 145, 106, 0.6)` → `rgba(7, 43, 31, 0.6)` | Origin, size, stops, and target element. |
| Green glow | `rgba(0, 154, 108, 0.15)`; offsets `9px 7px` and `-9px -7px`; `20px` blur | Target element and any spread value. |

## Typography

Font stack: `Aventa, Arial, sans-serif`.

Aventa is identified in the supplied notes as a licensed font. Use it only when an appropriately licensed copy is available; otherwise use the fallback stack. No font asset is included by this guide.

| Role | Size | Weight | Line height | Color / alignment |
| --- | --- | --- | --- | --- |
| H1 | `2.75rem` | Bold | `1.2` | White; centered in hero. |
| H2 | `2.25rem` | Bold | `1.2` | White; centered for section intros. |
| Card title | `1.75rem` | Regular | `1.2` | White; left-aligned. |
| Stat number | `2.625rem` | Regular | `1` | Green. |
| Intro text | `1.125rem` | Regular | `1.4` | Grey; centered for hero and section intros. |
| Body | `1rem` | Regular | `1.4` | Primary text; left-aligned in cards. |
| Small text and pills | `0.875rem` | Regular | `1.4` | Role-dependent; white in pills. |
| Button | `1rem` | Regular | `1` | White. |
| Footer links | `0.875rem` | Regular | `1` | Muted white. |

Letter spacing is normal throughout.

The supplied CSS observations also identify H1 at `3.25rem` and H2 at `2.875rem`. These may apply at other viewport widths, but their breakpoint mapping is unconfirmed. Do not assign them to particular breakpoints without further evidence or an explicit project design decision.

## Spacing, radius, and responsive layout

Spacing scale, in rem:

`0.25`, `0.375`, `0.75`, `1`, `1.25`, `1.5`, `2`, `2.5`, `3.75`, `5`, `6.25`.

| Element | Corner radius |
| --- | --- |
| Menu bars | `0.25rem` |
| Pills | `6px` |
| Team photos | `0.375rem` |
| Cards, stat tiles, and button | `0.75rem` |
| Logo tile, sized `72px` | `1.625rem` |

Observed breakpoint values: `991px`, `767px`, and `479px`. Exact layout changes and media-query directions were not supplied.

Hero and section introductions are centered. Card text is left-aligned. Grid lines establish the content frame without competing with the content.

## Components

### Header

- Logo on the left; menu icon on the right.
- Menu icon: three white bars, each `18px` wide and `2px` high.
- Bar spacing and header dimensions are unspecified.

### Value card

- Fill: white at 10%.
- Border: `1px` solid white at 10%.
- Radius: `0.75rem`.
- Padding: `2.5rem`.
- Left-aligned card title and body copy.

### Stat tile

- Radius: `0.75rem`.
- Padding: `1.25rem`.
- Hierarchy: pills at the top, then a green stat number, then a muted label.
- Do not infer a tile fill or border from the value-card styling without a project decision.

### Pill

- Fill: translucent green using the pill-fill color.
- Radius: `6px`.
- Padding: `10px` vertically and `0.75rem` horizontally.
- White text using the small-text typography.

### Contact button

- Radius: `0.75rem`.
- Padding: `0` vertically and `2.5rem` horizontally.
- White text using button typography.
- Height, background, border, and interaction states were not supplied. Zero vertical padding alone does not define the final button height.

### Team card

- Photo, then name, followed by muted title and location.
- A `3px` dot likely separates title and location; this placement is an inference.
- Photo radius: `0.375rem`.

## Motion

Most reported transitions use `0.2s ease`; some use `0.15s` and `0.4s`. Exact property and component assignments are unspecified. The green wave mesh is a visual reference; animation behavior has not been established.

For this project's implementation, respect reduced-motion preferences and keep motion secondary to invoice data and workflow feedback. This is an added project guideline, not an observed site behavior.

## Voice and copy

Short, confident, and aimed at engineers. Reference examples:

- “No Bureaucracy. Just Builders.”
- “Build Fast. Evolve Faster.”

The supplied examples favor outcomes and numbers, including `65%`, `3×`, and `99%`. These are style references, not substantiated metrics for this project. Show measured invoice counts and outcomes; label estimated savings and their assumptions explicitly.

For operational copy, use concise, specific language:

- “Invoice needs review.”
- “Requested 20 GadgetX; 5 available.”
- “Mock payment complete.”
- “Duplicate invoice. No additional payment.”

Avoid claiming a real payment, verified fraud, or measured business savings when the system has only simulated execution or detected an anomaly.

## Reference-site copy issues

The supplied notes flag these issues; they have not been independently verified:

- “measurable transparency, measurable results” is repetitive.
- “production - ready” contains stray spaces; use “production-ready.”

Do not carry these issues into project copy.

## Excluded scan artifacts

A blue-to-purple gradient and a text-to-speech animation were excluded from the supplied reference because they appeared to originate from a browser extension. Their origin is unconfirmed. They are not part of this project's style baseline.

## Applying the guide to the invoice application

These are proposed product adaptations, not claims about Galatiq's site:

- Use the black/white/green palette, thin framing lines, card radii, and spacing scale across the dashboard and invoice detail view.
- Keep invoice tables, validation findings, and audit evidence left-aligned and easy to scan. Reserve centered introductions and any wave mesh for an introductory area.
- Use green as a restrained accent. Communicate paid, rejected, review, and failed states with explicit labels and icons rather than color alone.
- Provide visible keyboard focus, readable contrast, and usable control sizes. Verify these on the actual rendered interface; the reference values alone do not establish accessibility compliance.
- Retain visible “Offline simulation,” “Live model,” and “Mock payment” labels where relevant.
- Treat missing hover, focus, disabled, loading, and error states as design work to complete during UI implementation.

## Implementation checklist

- [ ] Confirm font availability or use Arial/sans-serif fallbacks.
- [ ] Define shared color, typography, spacing, and radius tokens.
- [ ] Apply styles through maintainable application components and supported theme settings where available.
- [ ] Decide unresolved gradient usage, heading breakpoints, and component states explicitly.
- [ ] Verify dashboard, invoice details, and narrow-screen layouts visually.
- [ ] Check keyboard access, contrast, reduced motion, and status clarity.
- [ ] Keep displayed metrics and payment/model labels faithful to actual behavior.
