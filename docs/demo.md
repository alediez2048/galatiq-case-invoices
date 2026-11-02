# Evaluator walkthrough (offline CLI)

About 5 minutes. Everything runs in offline simulation with no network and no credentials. Ids, run ids and timestamps differ per run; the statuses, codes and amounts below were observed on 2026-11-01 (evaluation date pinned to 2026-01-31 so the results are repeatable).

Conventions: the CLI prints the result JSON on stdout and a one-line summary on stderr. The commands below show only the stderr summary (`>/dev/null`); drop that redirect to see the full JSON with findings, evidence and decision.

## 0. Setup

```bash
uv sync
uv run python scripts/demo_setup.py --db demo-offline.db
```

Creates a fresh seeded database (WidgetA 15, WidgetB 10, GadgetX 5, FakeItem 0). It refuses an existing path and never modifies or resets an existing database; to start over, pick a new path or delete the file yourself.

Shortcut used below:

```bash
run() { uv run python main.py --invoice_path=data/invoices/$1 --db demo-offline.db --evaluation-date 2026-01-31 >/dev/null; }
```

## 1. Clean invoice (1001)

```bash
run invoice_1001.txt
```

```
Paying Widgets Inc. USD 5,000.00 (idempotency_key=invoice:inv-...)
status=paid_mock run=run-... invoice=inv-... paid=USD 5,000.00
```

Point out: findings are only warnings/info (`terms_inconsistent`, `currency_assumed_usd`); decision `approved` by rule `R4_auto_approve`; a mock receipt for USD 5,000.00.

## 2. Rejection with evidence (1002, 1013)

```bash
run invoice_1002.txt
run invoice_1013.json
```

```
status=rejected run=run-... invoice=inv-...        (1002)
status=rejected run=run-... invoice=inv-...        (1013)
```

1002: blocker `quantity_exceeds_stock` for GadgetX, expected (available) 5, observed (requested) 20; no payment attempted, no receipt. 1013 (JSON with a PDF twin): blockers `total_mismatch` (stated 22,562.80 vs computed 22,512.80, a USD 50 discrepancy) and three `quantity_exceeds_stock` (WidgetA 22 vs 15, WidgetB 18 vs 10, GadgetX 9 vs 5). Both decisions are `rejected` by `R1_blocker`.

## 3. Messy formatting (1012)

```bash
run invoice_1012.txt
```

```
Paying QuickShip Distributers USD 9,975.00 (idempotency_key=invoice:inv-...)
status=paid_mock run=run-... invoice=inv-... paid=USD 9,975.00
```

Point out: the spaced-out title "I N V O I C E" is recorded as an `unparsed_line` info finding with its line number rather than silently dropped, and the currency was assumed (`currency_assumed_usd`, with the source snippet `SUBTOTAL:     $9,500.00`). Corrections carry evidence, not invented confidence scores.

## 4. EUR needs review (1014)

```bash
run invoice_1014.xml
```

```
status=needs_review run=run-... invoice=inv-...
```

Review findings `unsupported_currency` and `non_usd_currency` (observed `EUR`, evidence `/invoice/header/currency`); decision reasons `R2_non_usd`, `R2_review`. No payment, no silent conversion.

## 5. Duplicate across formats (1011 TXT then PDF)

```bash
run invoice_1011.txt
run invoice_1011.pdf
```

```
Paying Summit Manufacturing Co. USD 3,000.00 (idempotency_key=invoice:inv-...)
status=paid_mock run=run-... invoice=inv-X paid=USD 3,000.00
status=duplicate run=run-... invoice=inv-X paid=USD 3,000.00
```

The PDF resolves to the same invoice (same `inv-X`), the existing receipt (`rcpt-...`) is reused, there is no second "Paying" line, and `prior_run_id` in the JSON points at the TXT run.

## 6. Revision after payment (1004 then 1004 revised)

```bash
run invoice_1004.json
run invoice_1004_revised.json
```

```
Paying Precision Parts Ltd. USD 1,890.00 (idempotency_key=invoice:inv-...)
status=paid_mock run=run-... invoice=inv-Y paid=USD 1,890.00
status=needs_review run=run-... invoice=inv-Y
```

Same invoice id, but the revised document (USD 5,940.00) changes the content of an already-paid invoice: finding `revision_after_payment` (review severity, observed = the paid run id), no second payment.

## 7. Run everything into one ledger, with the table

Use a separate database so the steps above do not affect it:

```bash
uv run python scripts/demo_setup.py --db demo-all.db
uv run python scripts/demo_run_all.py --db demo-all.db
```

Observed (forward order):

```
file                       status        paid (USD)  reasons                                                                                         duplicate of
-------------------------  ------------  ----------  ----------------------------------------------------------------------------------------------  -----------------
invoice_1001.txt           paid_mock     5,000.00    -                                                                                               -
invoice_1002.txt           rejected      -           quantity_exceeds_stock                                                                          -
invoice_1003.txt           rejected      -           due_date_unresolved, zero_stock                                                                 -
invoice_1004.json          paid_mock     1,890.00    -                                                                                               -
invoice_1004_revised.json  needs_review  -           revision_after_payment                                                                          -
invoice_1005.json          rejected      -           quantity_exceeds_stock                                                                          -
invoice_1006.csv           paid_mock     2,750.00    -                                                                                               -
invoice_1007.csv           rejected      -           total_mismatch, quantity_exceeds_stock                                                          -
invoice_1008.txt           rejected      -           unknown_item                                                                                    -
invoice_1009.json          rejected      -           missing_vendor, missing_due_date, non_positive_quantity, non_positive_total, subtotal_mismatch  -
invoice_1010.txt           paid_mock     7,185.00    -                                                                                               -
invoice_1011.pdf           paid_mock     3,000.00    -                                                                                               -
invoice_1011.txt           duplicate     -           -                                                                                               invoice_1011.pdf
invoice_1012.pdf           paid_mock     9,975.00    -                                                                                               -
invoice_1012.txt           duplicate     -           -                                                                                               invoice_1012.pdf
invoice_1013.json          rejected      -           total_mismatch, quantity_exceeds_stock                                                          -
invoice_1013.pdf           duplicate     -           -                                                                                               invoice_1013.json
invoice_1014.xml           needs_review  -           unsupported_currency, non_usd_currency                                                          -
invoice_1015.csv           paid_mock     6,500.00    -                                                                                               -
invoice_1016.json          rejected      -           unknown_item                                                                                    -

documents processed : 20
runs in ledger      : 20
unique invoices     : 16
payments            : 7
mock-paid total     : USD 36,300.00
```

Point out: 20 documents and 20 runs but only 16 unique invoices, and 7 payments. In this order the PDF sorts before the TXT for 1011 and 1012, so the table shows the TXT as the duplicate (step 5 shows the opposite order). The run-order dependence is real: `--order reverse` pays the revised 1004 (USD 5,940.00) first and flags the original as the revision, giving a total of USD 40,350.00 with the same 7 payments and no identity paid twice. Exit status is non-zero if any run fails unexpectedly. Each subprocess runs with `INVOICE_NETWORK_GUARD=1`.

## Not yet covered

<!-- TODO(P6-03): UI walkthrough after P5-10 -->
UI steps (upload, invoice list/detail, review queue, high-value approval USD 10,000.01 vs 10,000.00, correction and stale-approval refusal, overview unique-vs-runs): pending.

<!-- TODO(P6-03): live pass after P3-10 -->
Live Grok pass (including the live-failure and explicit-retry step): pending credentials.
