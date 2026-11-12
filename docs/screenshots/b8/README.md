# B8 screenshots and state log (2026-11-13)

Before: commit of the B7 baseline (`feat/b7-complete`), before any B8 change. After: the same harness on `feat/b8-redesign`. Both runs use the same seeded records and viewports, so each pair is comparable.

## How they were captured

`cd web && SHOTS=before|after npx playwright test -c playwright.shots.config.ts b8` (`web/shots/b8.spec.ts`), headless in the installed Google Chrome, on the screenshot stack profile: database `matchdesk_shots`, API 8103, web 5175, Mailpit 1027/8027. The stack is created, seeded and dropped by the harness; `matchdesk_dev` and the owner's Mailpit are not touched. `measurements.json` in each folder holds the measured values.

## State log

| Shot | Role | Period | Fixture | State |
|---|---|---|---|---|
| `01-queue-{1440,1024,375}` | Clerk | October 2026 (top-bar period) | `seed_demo.py --preload`: receiving file imported (7 valid rows), 13 invoice PDFs uploaded and processed, FF-1006 and SS-5120 still in review, CT-25 conversion pending | Exception queue, default filters (open and pending approval), nothing selected |
| `01-queue-dark-1440` | Clerk | October 2026 | same | Same, dark theme |
| `02-ff1003-{1440,1024,375}` | Clerk | October 2026 | same | Match view of FF-1003 line 1 (Invoiced above received), opened from the queue, PDF rendered |
| `02-ff1003-dark-1440` | Clerk | October 2026 | same | Same, dark theme, invoice PDF on screen |
| `01-queue-dark-{1024,375}`, `02-ff1003-dark-{1024,375}` (after only) | Clerk | October 2026 | same | Dark theme at the other two widths |
| `03-approval-{1440,1024,375}` | Controller | October 2026 | same | Approvals with the CT-25 conversion waiting (1 CS = 25 EA) |
| `04-weekly-{1440,1024,375}` | Controller | Week of 5 Oct 2026 | same | Weekly summary, 5 to 11 October |
| `05-weekly-to-queue-1440` | Controller | Week of 5 Oct 2026 | same | The queue after choosing Fictional Fasteners' open count on the weekly summary |
| `06-operator-account-1440` | Operator (one-time code) | none | same | Operator account page of the demo tenant, no support access |

## Baseline walk on the owner's demo (`matchdesk_dev`, before any change)

Recorded in the in-app browser of the Claude desktop app at `http://127.0.0.1:5173` (both connected Chrome extensions were on other computers that cannot reach this machine's 127.0.0.1). Demo state at the start: PLAY.md sections 1 to 9 already played (receiving imported, 13 invoices, FF-1006 and SS-5120 confirmed, FF-1007 waived, CT-25 approved, report version 3 approved and governing); row counts recorded before any test run (`exceptions` 19, `backtest_reports` 3, `approvals` 1, `audit_events` 45). Nothing was changed on the demo during the walk.

1. **Clerk.** Queue: 8 open exceptions, CAD 1,037.30; the four coverage figures and the type counters sit above the table. FF-1003: the calculation sentence says "Received to date 60 EA. Invoiced to date 100 EA ... Excess 40 × 4.20 = 168.00"; the receipt (`receiving-warehouse-log.csv row 4`) is in a separate "Receipts and history" panel below the line comparison, linked to the whole import, not to the row. The decision was made on the screenshot stack, not on the demo.
2. **Controller.** Approvals: the conversion was already approved on the demo (pending on the screenshot stack). Weekly summary, 5 to 11 October: Fictional Fasteners 1 open exception, CAD 168.00. Its link opened `/exceptions?vendor=…`, which showed **2 exceptions, CAD 168.80** (FF-1003 and FF-1006 of 22 October): the week was dropped. Reports: versions 1 to 3, version 3 approved; the list does not say which version governs.
3. **Operator.** Console: one account, pilot CAD 500.00, paid, 14 billable units, support access none. Account page: the editable pilot form comes first; payment is a select inside it; support access is at the bottom.

## Measured (before)

- First actionable case at 375 × 812: its link starts at **1,528 px** (viewport 812 px), not visible without scrolling.
- Weekly drill-down: report 1 exception, CAD 168.00 for Fictional Fasteners; the queue showed 2 rows, CAD 330.00 (the month, not the week).
- FF-1003 receipt link at 1440 × 900: 855 px from the top, below the fold, in the receipts panel.

## Measured (after)

- First actionable case at 375 × 812: the case block starts at **300 px** and its **Review** control spans **387 to 427 px**: visible without scrolling, not covered, and it opens the case (`web/e2e/queue-b8.spec.ts`). The after harness measures the first visible case link, which is that Review control (387 px).
- Weekly drill-down: report 1 exception, CAD 168.00 for Fictional Fasteners; the queue it opens (`from=2026-10-05&to=2026-10-11`, supplier, open and pending approval) shows 1 row and "1 exception in this scope", 168.00.
- FF-1003 receipt link at 1440 × 900: 247 px from the top, beside "Received 60 EA" in the ledger line; it opens the receiving import with row 4 marked and a link back to the invoice.

Click path to FF-1003's supporting receipt (after): Exceptions → **Review** on FF-1003 → in the first line, under "Received 60 EA", `receiving-warehouse-log.csv row 4` → the import with row 4 (PO 4471, 4 Sept 2026, R-0904, 60 EA, counts as a receipt) marked → **Back to the invoice**.
