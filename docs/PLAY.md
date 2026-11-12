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
   - If no message arrives: after five requests for one address within 15 minutes (or twenty from this computer within an hour) no further link is sent. The page still says a link is on its way, on purpose, so nobody can learn which addresses exist. Wait, or run `make demo-reset`, which clears the counters.
4. The page asks "Sign in to MatchDesk as clerk.demo@example.invalid in this browser?". Choose **Sign in**. (Merely opening the link does nothing, so a mail scanner cannot use it up.) The first tab notices you are signed in too.

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
3. You land on the batch. The six counts always add up to 13. Within a few seconds: **10 ready, 2 need review, 0 failed, 1 duplicate file**. Of the two identical FF-1002 files, the one uploaded second is the duplicate. Files are sent in name order, so `FF-1002 copy.pdf` goes first and `FF-1002.pdf` is marked **Duplicate file**: "Same as FF-1002 copy.pdf", linked to the original's match view.

## 4. Fix what was misread

1. In the batch table, on the **FF-1006** row, choose **Review extraction**. The PDF is on the left, the values on the right. At the top: "Lines + tax = 0.80, document total 8.00".
2. Change **Total** to `0.80`. The check turns to "All arithmetic checks pass." The field carries an "edited" tag at once; **History** shows what was read.
3. Choose **Confirm and match**. You land on the match view for FF-1006; "Matching…" turns into the result without a reload: invoiced above received (CAD 0.80, 910 invoiced net against 900 received), and "Invoiced above ordered (by 10, cleared by a QuickBooks vendor credit)": FF-1004 billed the whole order of 1000 and a vendor credit of 100 brings the net back under it.
4. Choose **Invoices**, filter **State: Needs review**, open **SS-5120**. "Supplier not identified": choose **Synthetic Supply Co** as the supplier, then **Confirm and match**. (A missing supplier has to be filled in; the "document does not add up" box appears only when the arithmetic fails.) Its match view shows, greyed, "Billed against PO in QuickBooks: 1000. Not counted as a receipt."

## 5. Work the exception queue

1. Choose **Exceptions**. At the top: the receipt-coverage strip (live, before any report: "Receipt coverage 75% of invoiced PO lines" at this point, before the conversion is approved), then one counter per exception type (each is a filter), then the table, most valuable first. Filters live in the address bar, so Back and Refresh keep them. Where two exceptions sit on one line, the line's amount is counted once: the second shows CAD 0.00 with "counted under another exception".
2. Keyboard: **J** and **K** move between rows, **X** selects, **Enter** opens. Shortcuts can be turned off in the menu under your name.
3. Open **FF-1003** (Invoiced above received). The match view shows three panes: the invoice and its PDF, purchase order 4471 line 1, and the receipts with file and row (`receiving-warehouse-log.csv row 4`). The amber box gives the arithmetic: "Received to date 60 EA. Invoiced to date 100 EA (net of credit notes). Excess 40 × 4.20 = 168.00."
4. Back in the queue, choose the **No purchase order** counter and open **FF-1007**. In the bar at the bottom, **Resolve as: Waive**, note `PO 4999 does not exist; trivial amount`, then **Resolve and next**. Small waivers under the clerk's limit (CAD 100.00) take effect at once; larger ones go to the controller. The queue stays filtered: the **No purchase order** counter shows 0 and the table says 'No open exceptions of type "No purchase order".' with **Clear the filters**.
5. Try a bulk action: select two rows of the same type with **X** or the checkboxes, then **Resolve 2 items as…**. The dialog states the count and total before you confirm and reports each item's result by document number. A receipt-absent exception can never be waived in bulk.
6. **Aliases** shows the supplier codes mapped to our items. `CT-25` (Imaginary Packaging, 1 CS = 25 EA) is **Pending approval**: its invoices stay in exceptions until the controller approves the conversion.

Sign out from the menu under **Demo Clerk** (top right).

## 6. Sign in as the controller

Sign in with `controller.demo@example.invalid` as in step 1. Because approvals are waiting, you land on **Approvals**.

1. **Unit conversions**: "Approve conversion: 1 CS of Imaginary Packaging Inc code CT-25 = 25 EA of CT-1212." Choose **Approve**; the dialog restates the decision; choose **Approve** again. The IP-301 and IP-302 lines are re-matched.
2. If you loaded the invoices before the receiving file, a **Late receiving evidence** request is here too: approve it so those receipts count.
3. **New 1-to-1 aliases for review**: choose **Mark reviewed**. The list empties ("None.").

## 7. Approve the back-test report and download it

1. Choose **Reports**, keep **Test month: October 2026**, and choose **Create draft for October 2026**.
2. The violet banner says **DRAFT · version 1 · figures may change**. Read the cards (flagged discrepancies, of which not received, unverified, receipt coverage) and the seven sections. "Flagged discrepancies" always means findings plus not received, on this page and in the list of reports. If anything changes after the draft's data cut-off (a resolution, a re-match), approval is refused until you choose **Refresh draft**. If a yellow box lists what blocks approval (for example a re-match still running), wait a moment and choose **Refresh draft**.
3. **Export PDF** downloads the draft with DRAFT on every page.
4. Choose **Approve version N**. The dialog restates findings, not received and unverified totals; tick "I have reviewed the waived items" and approve. The banner turns dark: **APPROVED by Demo Controller**, and **Refresh draft** is gone (a new draft version is offered only if lines are re-matched later). Section 7 now shows the refund calculation on this approved version against the CAD 500.00 threshold.
5. **Export PDF** and **Export CSV** download the approved version.

## 8. Look around

- **Settings → Tolerances**: change a tolerance; before saving, MatchDesk says how many lines would be re-matched. A missing receiving record is always an exception, whatever the tolerance.
- **Settings → Users and support access**: invite a viewer (the invitation arrives in Mailpit).
- **Settings → Audit log**: every change with who, when, before and after; export as CSV.
- **Settings → QuickBooks connection**: the recorded-response mode is labelled; "Read now" reads the invented data again.
- Sign in as the clerk and open `http://127.0.0.1:5173/approvals`: "Your role does not include this page."
- Make the window narrow (phone width): checklist, approvals, reports and settings stay usable; work screens say "Open in a wider window to work on this."

## Not built yet (the screens say so)

- **Live QuickBooks.** The demo reads recorded, invented QuickBooks responses. The live connection is not built: it needs the owner's Intuit developer account and the sandbox check T-1.1.1 (`execution-plan.md`). The step that remains: the owner opens the Intuit developer account and sandbox company, T-1.1.1 records the real responses, then the live reader is written from them (TODO list in `TRD.md` section 11). Until then `MATCHDESK_QBO_MODE=intuit` refuses to start a sync, and the QuickBooks screen (S-04) says so.

Weekly summary (S-14), operator console (S-18), support access grants, pilot terms record, the "we have no receiving records" choice, email intake, deleting an invoice line in review.

## Start again

`make demo-reset` empties the local demo database and loads the demo company again. It only works on the local database `matchdesk_dev` and refuses in production.
