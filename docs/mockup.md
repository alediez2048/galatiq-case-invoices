# GALATIQ — Invoice Operations mockup

**Visual prototype:** [Open the interactive HTML mockup](mockups/index.html). The HTML includes the dashboard, invoice details, filters, review view, and a labeled sample-processing animation. It uses illustrative data and has no backend.

Status: proposed end experience. This is a Markdown wireframe and interaction specification, not a running UI or a record of processed invoices. All screen values below are illustrative, grounded in the supplied fixtures where identified.

References: [requirements](requirements.md), [constraints](contraints.md), [system design](systemsdesign.md), [technology stack](techstack.md), [style guide](styleguide.md).

## Product concept

**From invoice to decision. Every check visible.**

A compact workspace for an accounts-payable operator: submit a document, follow its progress, inspect the evidence, and understand the outcome. The dashboard answers three questions immediately: what has been processed, what needs attention, and what was paid through the mock payment service.

This is an operational application with Galatiq's visual language. Keep the brand introduction small enough that invoices and the primary action remain visible in the first viewport.

## Visual direction

- Pure black canvas with thin `#202020` framing lines; alternate `#070707` sections where useful.
- White titles, `#CFCFCF` supporting text, and muted white secondary labels.
- Green `#009A6C` for selected accents and metric numbers. Use text and distinct icons for statuses; green alone never communicates approval.
- A restrained green wave mesh in the initial empty-state introduction. Keep it out of invoice tables and evidence panels. This is a proposed decorative treatment, not a supplied asset.
- Aventa when licensed and available; otherwise Arial/sans-serif. Apply the type scale and component radii from the style guide.
- Proposed primary button: white text on green, with a visible focus outline and sufficient height. Verify rendered contrast and interaction states. This button fill is a project adaptation, not a confirmed reference-site style.
- Proposed desktop content width: up to 1,280px with 2rem outer spacing. Use the established spacing scale inside panels.
- Header uses a text wordmark until an approved logo asset is available. It identifies the case-study app without implying a deployed Galatiq product.

## Navigation and application frame

Three primary views: **Overview**, **Invoices**, and **Needs review**. An invoice opens a detail view with its evidence and history. A compact settings panel contains execution mode and readiness information.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ GALATIQ / Invoice Operations                    [Offline simulation] [Setup] │
├─────────────────────────────────────────────────────────────────────────────┤
│ Overview       Invoices       Needs review                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                        Active view content                                  │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Case-study prototype · Local workspace · All payments are simulated          │
└─────────────────────────────────────────────────────────────────────────────┘
```

The execution-mode badge stays visible. Individual historical runs retain their original mode even when the workspace mode changes. Settings never retroactively relabel results.

## Screen 1 — First visit / empty workspace

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ GALATIQ / Invoice Operations                    [Offline simulation] [Setup] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                  From invoice to decision.                                  │
│                     Every check visible.                                   │
│                                                                             │
│         Extract details. Check inventory. Review the decision.              │
│                      Simulate the payment.                                  │
│                                                                             │
│                 ~ restrained green wave mesh ~                              │
│                                                                             │
│              [Upload invoice]       [Try a sample]                           │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ No invoices processed yet.                                                  │
│ Start with a sample to explore the workflow.                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Try a sample** opens a selection panel, not an immediate processing action. Offer descriptive choices such as “Clean invoice,” “Stock mismatch,” “Messy formatting,” “Conflicting totals,” and “Unsupported currency,” alongside their invoice numbers. Labels describe the examples without claiming a run has already succeeded.

Setup readiness appears only when actionable: missing inventory setup, unsupported configuration, or missing live credentials. Initial database seeding can be automatic and idempotent. Do not expose SQL or internal graph configuration in the primary flow.

## Screen 2 — Add an invoice

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Add an invoice                                                   [Close]   │
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Drop an invoice here, or [Browse files]                                │ │
│ │ PDF, TXT, CSV, JSON, XML · Up to 10 MiB                                 │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ Selected: invoice_1001.txt                                      [Remove]    │
│ Mode: Offline simulation                                                    │
│ Local checks and simulated agent decisions. No external model calls.        │
│ Eligible invoices receive a mock payment automatically. No money moves.     │
│                                                                             │
│ [Cancel]                                              [Process invoice]     │
└─────────────────────────────────────────────────────────────────────────────┘
```

Use one invoice per submission in the MVP. Selecting or previewing a file never starts processing. Disable Process until the file and environment pass initial checks; show the specific reason next to the action.

In configured live mode, replace the mode explanation with: “Invoice content will be sent to the configured model provider. Payments remain simulated.” Model selection and credentials belong in setup, not in every upload interaction. Do not silently enable live mode.

## Screen 3 — Processing

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Processing invoice_1001.txt                          [Offline simulation]   │
│                                                                             │
│ ✓ Extract details    →    ● Check inventory    →    ○ Review    →    ○ Pay   │
│                                                                             │
│ Checking requested quantities against local inventory.                     │
│                                                                             │
│ Completed                                                                   │
│ ✓ Vendor, invoice number, due date, and two items extracted.                │
│ ✓ Amounts normalized.                                                       │
│                                                                             │
│ Payment has not been attempted.                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

Symbols pair with text: complete, active, pending, failed, or skipped. Update stages only when actual workflow events arrive; do not animate invented percentages, timings, tool calls, or model activity. Offline mode explicitly labels recommendations as simulated.

An extraction retry displays “Checking an extraction issue — attempt 2 of 2.” Approval critique displays “Checking the recommendation against policy.” Once a terminal result is available, open the detail view.

Do not offer cancellation or background execution unless the implementation can reliably honor those controls. Prevent double submission while processing; persistent payment checks remain the final safeguard against repeated actions.

## Screen 4 — Overview with results

Illustrative snapshot: four unique invoices have each been processed once. Two received mock payments, one was rejected, and one needs review. No duplicates or failed runs are included in this example.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Invoice overview                                          [Add invoice]    │
│ A clear view of every decision.                                             │
│                                                                             │
│ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌───────────────┐ │
│ │ 4              │ │ 2              │ │ 1              │ │ 1             │ │
│ │ Unique invoices│ │ Mock paid      │ │ Needs review   │ │ Rejected      │ │
│ └────────────────┘ └────────────────┘ └────────────────┘ └───────────────┘ │
│                                                                             │
│ Mock paid: USD 6,890.00                       No real funds transferred.    │
│                                                                             │
│ Recent invoices                                                             │
│ Invoice   Vendor                    Total          Outcome           Open  │
│ INV-1001  Widgets Inc.               USD 5,000.00   ✓ Mock paid         →   │
│ INV-1004  Precision Parts Ltd.       USD 1,890.00   ✓ Mock paid         →   │
│ INV-1002  Gadgets Co.                USD 15,000.00  × Rejected          →   │
│ INV-1014  TechParts International    EUR 4,125.00   ! Needs review      →   │
│                                                                             │
│ [View all invoices]                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

Counts come from unique invoice identities and current business outcomes. Processing attempts, alternate source files, and duplicate submissions are shown separately in run history. Add a Failed count/filter when failures exist; never hide failures to preserve the four-card arrangement. During active work, show processing separately.

Sum mock-paid amounts by currency, never combine USD and EUR. Avoid savings claims in the MVP; any later time/cost estimates need visible assumptions and separate labeling from measured results.

## Screen 5 — Invoice detail: successful outcome

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ ← Invoices                                                                 │
│ INV-1001 · Widgets Inc.                                  [✓ Mock paid]     │
│ USD 5,000.00 · Due Feb 1, 2026 · Offline simulation                          │
│                                                                             │
│ ✓ Extracted          ✓ Validated          ✓ Approved          ✓ Mock paid  │
├───────────────────────────────────┬─────────────────────────────────────────┤
│ Source                            │ Decision                                │
│ invoice_1001.txt                  │ Mock payment complete.                  │
│                                   │ Inventory and totals passed.            │
│ INVOICE                           │ No unresolved payment blockers.         │
│ Vendor: Widgets Inc.              │                                         │
│ Invoice Number: INV-1001           │ [Decision] [Checks] [History]           │
│ ...                               │                                         │
│                                   │ Required fields        ✓ Complete       │
│ [View full source]                │ Item quantities        ✓ Within stock   │
│                                   │ Invoice arithmetic     ✓ Matches        │
│                                   │ Duplicate payment      ✓ None found     │
├───────────────────────────────────┴─────────────────────────────────────────┤
│ Line items                                                                  │
│ Item           Requested       Available       Unit price       Line total │
│ WidgetA        10              15              USD 250.00       USD 2,500  │
│ WidgetB        5               10              USD 500.00       USD 2,500  │
│                                                                             │
│ Mock receipt                                                                │
│ Amount: USD 5,000.00 · No real funds transferred                             │
│ [View receipt]                                     [Download result JSON]   │
└─────────────────────────────────────────────────────────────────────────────┘
```

This example shows fixture-derived values, not a completed payment. Actual receipts show their persisted reference and processing time only after success. If the evaluation date is after the due date, display an “Overdue” warning with the evaluation date; historical fixtures are not automatically rejected for that reason.

For PDF inputs, show a page preview when supported. For TXT, CSV, JSON, and XML, show readable source text/rows with evidence references. A failed visual preview does not imply extraction succeeded; provide available extracted text and a clear preview limitation.

**Decision tab:** concise recommendation, critique summary, final policy result, and execution mode. **Checks tab:** observed versus expected values and source references. **History tab:** actual stage events and prior runs. Do not present private model reasoning or decorative “thinking” transcripts.

## Screen 6 — Invoice detail: rejection

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ INV-1002 · Gadgets Co.                                     [× Rejected]    │
│ USD 15,000.00 · Offline simulation                                          │
│                                                                             │
│ Payment blocked: requested quantity exceeds available stock.               │
│                                                                             │
│ Item           Requested       Available       Result                       │
│ GadgetX        20              5               Exceeds stock by 15          │
│                                                                             │
│ Decision: Reject                                                            │
│ Critique: High-value review does not resolve the stock mismatch.            │
│ Payment: Not attempted                                                      │
│                                                                             │
│ [View source evidence]  [Download result JSON]  [Add corrected invoice]     │
└─────────────────────────────────────────────────────────────────────────────┘
```

“Add corrected invoice” opens the normal submission flow. It does not erase the previous result or bypass revision checks. Show the correction requirement plainly. Do not offer an “Approve anyway” action.

## Screen 7 — Needs review

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Needs review                                                                │
│ Unresolved invoices. No payment has been made for these examples.           │
│                                                                             │
│ Invoice    Vendor                    Reason                         Open    │
│ INV-1014   TechParts International    EUR settlement unsupported      →     │
│                                                                             │
│ Selected invoice                                                            │
│ Total: EUR 4,125.00                                                          │
│ Inventory and arithmetic passed.                                            │
│ This prototype only simulates USD settlement.                               │
│                                                                             │
│ [View invoice]                                      [Download result JSON]  │
│                                                                             │
│ Review resolution is not available in this prototype.                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

The MVP review queue explains unresolved decisions and exposes evidence; it has no approval/rejection controls. Missing information and ambiguous corrections may also appear here.

For a revised invoice whose original was already paid, use specific copy: “Earlier version already mock paid. Revised version blocked from additional payment.” Show the prior receipt. Do not use the blanket “no payment has been made” wording for that case.

## Other essential states

| State | Visible message | Next action / behavior |
| --- | --- | --- |
| Exact duplicate or alternate format with identical payable content | “Already processed. No additional payment.” | Open prior result and receipt if one exists. Distinguish this submission from the original outcome. |
| Changed version under an existing invoice identity | “Invoice versions differ. Review required.” | Show compared totals, changed lines, and prior payment state; no automatic replacement. |
| Malformed or unsupported input | “We could not read this invoice.” plus a specific cause | Replace file. No payment or fabricated extracted fields. |
| Image-only PDF without OCR support | “This PDF needs OCR, which this prototype does not support.” | Submit a text-based version or inspect source outside the app. |
| Oversized input | “File exceeds the 10 MiB limit.” | Choose a smaller file; do not start a run. |
| Missing required fields | “Vendor and due date are missing.” | Show missing fields; no invented values or payment. Additional hard failures may instead lead to rejection. |
| Contradictory totals | “Stated total exceeds calculated total by USD 50.00.” | Show calculation and source values; block payment. |
| Live provider unavailable | “Model request failed. Payment was not attempted.” | Explicit retry, or explicitly select offline mode for a new run; no silent fallback. |
| Processing failure | “Processing stopped during validation.” plus actionable detail | Retry safely; retain failure history and reveal any persisted payment outcome before retrying a payment-stage error. |
| Empty filtered list | “No invoices match these filters.” | Clear filters. |
| Loading history | “Loading invoice history…” | Keep existing context visible; avoid fabricated records. |

## Screen behavior and accessibility

- Keyboard users can reach navigation, upload controls, filters, rows, tabs, and downloads. An opened panel has a meaningful heading and returns focus to its trigger when closed.
- Use text labels with status icons. Never make color the only indication of outcome, active stage, or validation failure.
- Monetary values are right-aligned; currency is explicit. Use legible tabular figures where the selected font supports them.
- Long vendor names wrap or truncate with an accessible full label. Tables have clear headers and sensible reading order.
- Use short `0.2s ease` transitions for simple state changes. Respect reduced motion and avoid mandatory animated decoration.
- Error messages appear next to the relevant field or action. Announce asynchronous completion/failure without repeatedly interrupting screen readers.
- Downloads expose persisted results, not transient UI state. Routine view changes and Streamlit reruns must never initiate processing or payment.

## Responsive layout proposal

These are proposed project behaviors using the style guide's breakpoint values, not verified behavior of the reference site.

| Width | Layout |
| --- | --- |
| Above 991px | Horizontal navigation, four metric cards when space permits, two-column source/decision detail. |
| 768–991px | Two metric columns; narrower source/decision layout or stacked panels based on content. |
| 480–767px | Compact navigation, stacked detail panels, horizontally scrollable line-item table, two metric columns where legible. |
| 479px and below | One metric column, invoice summary cards instead of the wide list, full-width primary action, vertically stacked fields. |

On small screens, show the outcome and primary reason before the source preview. Preserve access to every evidence field and full line-item data; hiding columns must not hide information permanently.

## Suggested evaluator walkthrough

Each step describes an expected demo outcome to implement and verify, not an already-tested result.

1. Open the empty workspace in offline simulation and select the clean invoice sample.
2. Process INV-1001; inspect inventory checks, approval critique, and the USD 5,000 mock receipt.
3. Process INV-1002; see GadgetX 20 requested versus 5 available and payment not attempted.
4. Process INV-1012; inspect evidence-backed formatting corrections without presenting invented confidence percentages.
5. Process INV-1013; inspect aggregated stock shortages and the USD 50 total discrepancy.
6. Process INV-1014; see explicit EUR currency and the unresolved review status.
7. Resubmit INV-1001; confirm that the existing receipt is reused and mock-paid totals do not increase.
8. Return to the overview and distinguish unique invoices from processing attempts.

Use fresh, explicitly initialized demo data for a repeatable walkthrough. Do not silently reset the user's existing local ledger.

## MVP boundary and implementation handoff

Build the frame, upload/sample selection, real stage progress, invoice list/detail, result download, and read-only review queue first. The UI calls the shared processing service described in [system design](systemsdesign.md); it must not duplicate business rules.

Later extensions could add audited human review actions, richer invoice-version comparison, batch submission, and measured business-impact analysis. These are outside the current mockup's required interactive scope.

Before considering the experience complete, visually inspect empty, loading, successful, rejected, review, duplicate, and error states at desktop and narrow widths. Replace every illustrative value with actual persisted data, verify mock/live labeling, and confirm that all visible controls perform the promised action.
