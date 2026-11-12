# Play through MatchDesk (local demo)

A step-by-step script to use the whole product yourself, first as the **clerk**, then as the **controller**. Everything is invented: the company, suppliers, purchase orders, invoices and people. Nothing leaves this computer; no real QuickBooks, mail or storage account is used.

Time needed: about 20 minutes.

## 0. Start

From the `matchdesk-ap` folder, in a terminal:

```
make up            # PostgreSQL, Redis, Mailpit and MinIO must already be running
make demo-reset    # empties the local demo database and loads the demo company (asks nothing)
make web           # the web app on http://127.0.0.1:5173 (leave this running)
```

`make demo-reset` prints the two people you can sign in as:

| Person | Email | Role |
|---|---|---|
| Demo Clerk | `clerk.demo@example.invalid` | Clerk: uploads, corrects, resolves |
| Demo Controller | `controller.demo@example.invalid` | Controller: approves, signs the report |

It also writes the files you will upload into **`play-files/`** in the `matchdesk-ap` folder:

- `play-files/receiving-warehouse-log.csv`: the warehouse receiving log (8 rows, one of them for a purchase order that does not exist).
- `play-files/invoices/`: 13 invoice PDFs for October 2026 from three invented suppliers. One is a byte-identical copy (`FF-1002 copy.pdf`), one prints a wrong total (`FF-1006`), one has no supplier name (`SS-5120`).

The demo company is already connected to QuickBooks in **recorded-response mode**: it reads invented QuickBooks data recorded for the demo, and the screen says so.

Use Google Chrome or another Chromium browser at `http://127.0.0.1:5173` (use exactly this address, not `localhost`).

## 1. Sign in as the clerk

1. Open `http://127.0.0.1:5173`. You land on **Sign in**.
2. Type `clerk.demo@example.invalid` and choose **Email me a sign-in link**.
3. The page says a link is on its way and, because this is a development build, shows a note: "Local development: open Mailpit to get your link". Open Mailpit at `http://127.0.0.1:8025`, open the newest message "Your MatchDesk sign-in link", and click the link. It opens in a new tab.
4. Choose **Sign in**. (Merely opening the link does nothing, so a mail scanner cannot use it up.) The first tab notices you are signed in too.

You see the **Onboarding checklist**: QuickBooks is connected and 7 purchase orders were read; receiving and invoices are "Not started".

## 2. Load the receiving file

1. Choose **Receiving** in the top bar.
2. Under **Load a receiving file**: choose `play-files/receiving-warehouse-log.csv`, keep **Warehouse receiving log** and **A · Warehouse record**, type `Demo Receiver` under "Who keeps this record", then **Upload and preview**.
3. **1. Match the columns**: MatchDesk has already matched PO, Line, Qty, UOM, Received and Receiver from the headers. The first rows are shown. Choose **Check rows**.
4. **2. Validation result**: "7 rows valid, 1 rejected." Row 9 is rejected: "Unknown PO number" (4999). You can download the rejected rows.
5. **3. Coverage**: keep "Every delivery between these dates is in this file" (1 Aug to today). This is what lets MatchDesk say "not received" when the log shows nothing.
6. Choose **Import 7 valid rows**. Each receipt line now shows its PO, date, row and "Counts as a receipt: Yes".

## 3. Upload the invoices

1. Choose **Intake**.
2. Drag all 13 files from `play-files/invoices/` onto the box (or **Choose files** and select them all).
3. You land on the batch. The six counts always add up to 13. Within a few seconds: **10 ready, 2 need review, 0 failed, 1 duplicate file**. The copy says "Same as FF-1002.pdf".

## 4. Fix what was misread

1. In the batch table, on the **FF-1006** row, choose **Review extraction**. The PDF is on the left, the values on the right. At the top: "Lines + tax = 0.80, document total 8.00".
2. Change **Total** to `0.80`. The check turns to "All arithmetic checks pass." The field now carries an "edited" tag; **History** shows what was read.
3. Choose **Confirm and match**. You land on the match view for FF-1006; "Matching…" turns into the result without a reload.
4. Choose **Invoices**, filter **State: Needs review**, open **SS-5120**. "Supplier not identified": choose **Synthetic Supply Co** as the supplier, then **Confirm and match**.

## 5. Work the exception queue

1. Choose **Exceptions**. At the top: the receipt-coverage strip, then one counter per exception type (each is a filter), then the table, most valuable first. Filters live in the address bar, so Back and Refresh keep them.
2. Keyboard: **J** and **K** move between rows, **X** selects, **Enter** opens. Shortcuts can be turned off in the menu under your name.
3. Open **FF-1003** (Invoiced above received). The match view shows three panes: the invoice and its PDF, purchase order 4471 line 1, and the receipts with file and row (`receiving-warehouse-log.csv row 4`). The amber box gives the arithmetic: "Received to date 60 EA. Invoiced to date 100 EA (net of credit notes). Excess 40 × 4.2 = 168.00."
4. Back in the queue, choose the **No purchase order** counter and open **FF-1007**. In the bar at the bottom, **Resolve as: Waive**, note `PO 4999 does not exist; trivial amount`, then **Resolve and next**. Small waivers under the clerk's limit (CAD 100.00) take effect at once; larger ones go to the controller.
5. Try a bulk action: select two rows of the same type with **X** or the checkboxes, then **Resolve 2 items as…**. The dialog states the count and total before you confirm and reports each item's result. A receipt-absent exception can never be waived in bulk.
6. **Aliases** shows the supplier codes mapped to our items. `CT-25` (Imaginary Packaging, 1 CS = 25 EA) is **Pending approval**: its invoices stay in exceptions until the controller approves the conversion.

Sign out from the menu under **Demo Clerk** (top right).

## 6. Sign in as the controller

Sign in with `controller.demo@example.invalid` as in step 1. Because approvals are waiting, you land on **Approvals**.

1. **Unit conversions**: "Approve conversion: 1 CS of Imaginary Packaging Inc code CT-25 = 25 EA of CT-1212." Choose **Approve**; the dialog restates the decision; choose **Approve** again. The IP-301 and IP-302 lines are re-matched.
2. If you loaded the invoices before the receiving file, a **Late receiving evidence** request is here too: approve it so those receipts count.
3. **New 1-to-1 aliases for review**: choose **Mark reviewed**.

## 7. Approve the back-test report and download it

1. Choose **Reports**, keep **Test month: October 2026**, and choose **Create draft for October 2026**.
2. The violet banner says **DRAFT · version 1 · figures may change**. Read the cards (flagged discrepancies, not received, unverified, receipt coverage) and the seven sections. If a yellow box lists what blocks approval (for example a re-match still running), wait a moment and choose **Refresh draft**.
3. **Export PDF** downloads the draft with DRAFT on every page.
4. Choose **Approve version N**. The dialog restates findings, not received and unverified totals; tick "I have reviewed the waived items" and approve. The banner turns dark: **APPROVED by Demo Controller**. Section 7 now shows the refund calculation on this approved version against the CAD 500.00 threshold.
5. **Export PDF** and **Export CSV** download the approved version.

## 8. Look around

- **Settings → Tolerances**: change a tolerance; before saving, MatchDesk says how many lines would be re-matched. A missing receiving record is always an exception, whatever the tolerance.
- **Settings → Users and support access**: invite a viewer (the invitation arrives in Mailpit).
- **Settings → Audit log**: every change with who, when, before and after; export as CSV.
- **Settings → QuickBooks connection**: the recorded-response mode is labelled; "Read now" reads the invented data again.
- Sign in as the clerk and open `http://127.0.0.1:5173/approvals`: "Your role does not include this page."
- Make the window narrow (phone width): checklist, approvals, reports and settings stay usable; work screens say "Open in a wider window to work on this."

## Not built yet (the screens say so)

Weekly summary (S-14), operator console (S-18), support access grants, pilot terms record, the "we have no receiving records" choice, email intake, deleting an invoice line in review.

## Start again

`make demo-reset` empties the local demo database and loads the demo company again. It only works on the local database `matchdesk_dev` and refuses in production.
