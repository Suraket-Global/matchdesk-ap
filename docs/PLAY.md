# Play through MatchDesk (local demo)

A step-by-step script to use the whole product yourself, first as the **clerk**, then as the **controller**. Everything is invented: the company, suppliers, purchase orders, invoices and people. Nothing leaves this computer; no real QuickBooks, mail or storage account is used.

Time needed: about 30 minutes.

## 0. Start

From the `matchdesk-ap` folder, in a terminal:

```
make up            # PostgreSQL, Redis, Mailpit and MinIO must already be running
make demo-reset    # empties the local demo database and loads the demo company (asks nothing)
make web           # the web app on http://127.0.0.1:5173 (leave this running)
```

`make demo-reset` prints the three people you can sign in as:

| Person | Email | Role |
|---|---|---|
| Demo Clerk | `clerk.demo@example.invalid` | Clerk: uploads, corrects, resolves |
| Demo Controller | `controller.demo@example.invalid` | Controller: approves, signs the report |
| Demo Operator | `operator.demo@example.invalid` | MatchDesk staff: pilot records and support access (section 9) |

The operator also needs a one-time code. `make demo-reset` prints a TOTP secret for an authenticator app (local demo only, invented), or run `make operator-code` to print the current code.

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

You see the **Onboarding checklist**. It opens with your next task, **Load the warehouse receiving file**, and the columns that file needs, with the button to load it. QuickBooks is connected and 7 purchase orders were read; receiving and invoices are "Not started".

## 2. Load the receiving file

1. Choose **Receiving** in the sidebar on the left (under Work).
2. Under **Load a receiving file**: choose `play-files/receiving-warehouse-log.csv`, keep **Warehouse receiving log** and **A · Warehouse record**, type `Demo Receiver` under "Who keeps this record", then **Upload and preview**.
3. **1. Match the columns**: MatchDesk has already matched PO, Line, Qty, UOM, Received and Receiver from the headers. The first rows are shown. Choose **Check rows**.
4. **2. Validation result** leads with "7 valid rows, 1 rejected". Row 9 is rejected: "Unknown PO number" (4999), shown with its original row (`4999, 1, 10, , 2026-10-28, R-1028`). You can download the rejected rows. The column matching folds away below; open it to change a column and check again.
5. **3. Coverage**: keep "Every delivery between these dates is in this file" (1 Aug to today). This is what lets MatchDesk say "not received" when the log shows nothing.
6. Choose **Import 7 valid rows**. Each receipt line now shows its PO, date, row and "Counts as a receipt: Yes".

## 3. Upload the invoices

1. Choose **Intake** in the sidebar.
2. Drag all 13 files from `play-files/invoices/` onto the box (or **Choose files** and select them all).
3. You land on the batch. The six counts always add up to 13. Within a few seconds: "13 files read: **10 ready, 2 need review, 0 failed, 1 duplicate**." The batch then leads with **Review 2 invoices** (FF-1006 and SS-5120, each with **Review extraction**); the duplicate is listed under it with its provenance, and the 10 ready files fold below. Files are listed in name order. Of the two identical FF-1002 files, the one that arrives second (four files are sent at a time) is marked **Duplicate file**, "Same as …" the other, linked to the original's match view.

## 4. Fix what was misread

1. Under **Review 2 invoices**, on the **FF-1006** row, choose **Review extraction**. The PDF is on the left, the values on the right. At the top: "Lines + tax = 0.80, document total 8.00", and a row of four figures: printed on the document 8.00, lines + tax 0.80, the total field, and the result "Differs by 7.20".
2. Change **Total** to `0.80`. The check turns to "All arithmetic checks pass."; the row says "Adds up" and "You changed the total from 8.00 to 0.80". The field carries an "edited" tag at once; **History** shows what was read.
3. Choose **Confirm and match**. You land on the match view for FF-1006; "Matching…" turns into the result without a reload: invoiced above received (CAD 0.80, 910 invoiced net against 900 received), and "Invoiced above ordered (by 10, cleared by a QuickBooks vendor credit)": FF-1004 billed the whole order of 1000 and a vendor credit of 100 brings the net back under it.
4. Choose **Invoices**, filter **State: Needs review**, open **SS-5120**. "Supplier not identified": choose **Synthetic Supply Co** as the supplier, then **Confirm and match**. (A missing supplier has to be filled in; the "document does not add up" box appears only when the arithmetic fails.) Its match view shows, greyed, "Billed against PO in QuickBooks: 1000. Not counted as a receipt."

## 5. Work the exception queue

1. Choose **Exceptions** (the sidebar shows how many are open in every period). At the top, the scope as chips: **Dates** October 2026 (the test month in the top bar) and **Status** Open and pending approval; then the filters, one tab per exception type with its count, and the list, most valuable first: invoice and supplier, why it needs you, PO and item, quantity difference, amount and **Review**. The footer gives the count and value of the whole scope. Filters live in the address bar, so Back and Refresh keep them, and each chip can be removed on its own. Where two exceptions sit on one line, the line's amount is counted once: the second shows 0.00 with "counted under another exception". Receipt coverage ("75%" at this point, before the conversion is approved) and **Why counts differ between screens** are below the list. At phone width each exception is a block with its **Review** button, and the filters open with **Filters**.
2. Keyboard: **J** and **K** move between rows, **X** selects, **Enter** opens. Shortcuts can be turned off in the menu under your name.
3. Choose **Review** on **FF-1003** (Invoiced above received). The first line of the match view reads **Billed to date 100 EA − Received 60 EA = Excess 40 EA × Unit price CAD 4.20 = Exposure CAD 168.00**. Under "Received" the link `receiving-warehouse-log.csv row 4` opens the receiving import with row 4 marked and **Back to the invoice**. Below: the invoice PDF (**Fit width**, expand, zoom), the arithmetic sentence and line comparison, the receipts, and on the right the resolution form and purchase order 4471 line 1. Choosing a resolution says what it does before you submit it. The crumb names the queue you came from ("Exception queue: October 2026"); **Previous**, **Next** and "3 of 8" follow that queue's order.
4. Back in the queue, choose the **No purchase order** tab and **Review** on **FF-1007**. In the action panel on the right, **Resolve as: Waive**, note `PO 4999 does not exist; trivial amount`, then **Resolve and return to the queue** (it is the last one of that type). Small waivers under the clerk's limit (CAD 100.00) take effect at once; larger ones go to the controller. The queue stays filtered, with FF-1007's row position kept: the **No purchase order** tab shows 0 and the table says 'No open exceptions of type "No purchase order".' with **Clear the filters**.
5. Try a bulk action: select two rows of the same type with **X** or the checkboxes, then **Resolve 2 items as…** in the dark bar that appears above the table. The dialog states the count and total before you confirm and reports each item's result by document number. A receipt-absent exception can never be waived in bulk.
6. **Aliases** shows the supplier codes mapped to our items. `CT-25` (Imaginary Packaging, 1 CS = 25 EA) is **Pending approval**: its invoices stay in exceptions until the controller approves the conversion.

Sign out from the menu under **Demo Clerk** (top right).

## 6. Sign in as the controller

Sign in with `controller.demo@example.invalid` as in step 1. Because approvals are waiting, you land on **Approvals**.

1. **Unit conversions**: the request reads in four parts. Proposed change **1 CS = 25 EA** (Imaginary Packaging Inc code CT-25 becomes CT-1212); affected records IP-301 line 1 (8 CS, 200 EA after conversion) and IP-302 line 1 (4 CS, 100 EA), with the exceptions open on them now; what approving does (2 lines on 2 invoices matched again in EA); the decision. Choose **Approve**; the dialog restates the decision; choose **Approve** again. The IP-301 and IP-302 lines are re-matched.
2. If you loaded the invoices before the receiving file, a **Late receiving evidence** request is here too: approve it so those receipts count.
3. **New 1-to-1 aliases for review**: choose **Mark reviewed**. The list empties ("None.").

## 7. Approve the back-test report and download it

1. Choose **Reports**, keep **Test month: October 2026**, and choose **Create draft for October 2026**.
2. The violet banner says **DRAFT · version 1 · figures may change**; the list of reports names it as the next decision. Read the cards (flagged discrepancies, of which not received, unverified, receipt coverage) and the seven sections. "Flagged discrepancies" always means findings plus not received, on this page and in the list of reports. If anything changes after the draft's data cut-off (a resolution, a re-match), approval is refused until you choose **Refresh draft**. If a yellow box lists what blocks approval (for example a re-match still running), wait a moment and choose **Refresh draft**.
3. **Export PDF** downloads the draft with DRAFT on every page.
4. Choose **Approve version N**. The dialog restates the figures with one label each: "Flagged discrepancies CAD … (findings CAD … + not received CAD …)", unverified, and how many items are still open in the queue; tick "I have reviewed the waived items" and approve. The banner turns dark: **APPROVED by Demo Controller**, and **Refresh draft** is gone (a new draft version is offered only if results change after the data cut-off; an identical one is refused). Section 7 shows the pilot terms and the refund calculation on this version against the threshold of the signed terms (CAD 500.00).
5. In section 7 choose **Make version N the governing version**. The dialog says this is decided once; confirm. Section 7 now reads "This version" with the stored refund result; the banner says **GOVERNING VERSION** and the list of reports marks it **Governing**; **Getting started** shows it under Pilot terms. It cannot be changed later.
6. **Export PDF** and **Export CSV** download the approved version. The CSV uses the same words as the screen (flagged discrepancies, findings, not received; Yes or No; types and statuses in words).

## 8. Look around

- **Tolerances** (sidebar, Setup): change a tolerance; before saving, MatchDesk says how many lines would be re-matched. A missing receiving record is always an exception, whatever the tolerance.
- **Users and access** (sidebar, Setup): invite a viewer (the invitation arrives in Mailpit).
- **Audit log** (sidebar, Setup): every change with who, when, before and after; export as CSV.
- **QuickBooks** (sidebar, Setup; or "QuickBooks: demo data" in the top bar): the source is labelled Demo data, with the last read the server recorded (and its failure, if one failed); "Read now" reads the invented data again.
- Sign in as the clerk and open `http://127.0.0.1:5173/approvals`: "Your role does not include this page."
- Make the window narrow (phone width): the sidebar folds behind the menu button; the exception queue becomes one block per case with its **Review** button in the first screen, the match view stacks the calculation first; checklist, approvals, reports and settings stay usable and wide tables become cards; extraction review, the receiving column step, intake upload, aliases and tolerances still say "Open in a wider window to work on this."
- Choose **Theme** in the menu under your name to switch between light and dark, and the **Period** in the top bar to change the month the screens start from.

## 9. Weekly summary, email intake, operator and support access (B7)

1. **Weekly summary** (sidebar, Review), as the controller: choose the week of 5 October 2026 (the date box or the arrows). One row per supplier: documents, lines, how many passed every check, flagged discrepancies, open exceptions and their value. Fictional Fasteners Ltd shows 1 open exception, CAD 168.00. Choose that **1**: the queue opens with **Dates 5 to 11 Oct 2026 (weekly summary)**, **Supplier Fictional Fasteners Ltd** and status open and pending approval, and shows the same 1 exception and CAD 168.00 (FF-1006, dated 22 October, is outside the week). Remove the supplier chip and the dates stay; refresh and Back keep the scope. A week with no invoices says "Nothing checked for this week" instead of zeros. **Email this week now** sends the totals and a link (no supplier, price or line) to the controllers: open Mailpit to read it. The same email goes out by itself every Monday morning for the week before.
2. **Invoices by email**: in a terminal run `make demo-email`. It posts two invented, signed emails to the account's intake address `demo-invoices@intake.matchdesk.invalid`. Open **Intake**: under **Invoices by email**, one from `billing@fictional-fasteners.example` (an allowed sender) is already in a new batch (source Email); one from `accounts@unknown-supplier.example` is **Held for you**. Choose **Release into a batch** (or **Discard**). As the controller you can allow another sender or a whole domain.
3. **Operator console**: sign out, then sign in as `operator.demo@example.invalid`. After the link, the page asks for the one-time code: run `make operator-code` and type it. You see **Operator console**: the demo account with its pilot, payment, billable units (one per invoice or credit note, in the month it was first read) and support access. Open the account: it starts with payment (Paid, CAD 500.00 pilot), the pilot period and outcome, support access and billable units. Below, edit the pilot record (for example the signed-terms reference) and **Save pilot record**. Under **Support access**, give a reason and **Ask for support access**. You cannot open any of the account's documents.
4. **Grant it**: sign in as the controller, **Users and access** (sidebar, Setup): the request is there with its length and reason. **Grant 1 day**; the dialog says what it allows. The audit log records the request and the grant.
5. **Read only visit**: sign in as the operator again (a new one-time code), open the account and choose **Open the account, read only**. A violet banner on every screen, which stays in view while you scroll, says "Support access, read only" and until when; nothing can be changed. **Leave the account** returns to the console. As the controller, **End access now** ends it at once.

## Not built yet (the screens say so)

- **Live QuickBooks.** The demo reads recorded, invented QuickBooks responses. The live connection is not built: it needs the owner's Intuit developer account and the sandbox check T-1.1.1 (`execution-plan.md`). The step that remains: the owner opens the Intuit developer account and sandbox company, T-1.1.1 records the real responses, then the live reader is written from them (TODO list in `TRD.md` section 11.1). Until then `MATCHDESK_QBO_MODE=intuit` refuses to start a sync, and the QuickBooks screen (S-04) says so.
- **Hosted email provider.** Email intake works with the local signed webhook (`make demo-email`). A real inbound address needs an email provider account; `MATCHDESK_INBOUND_PROVIDER` set to a provider refuses until then.
- Not built, no outside account needed: the "we have no receiving records" choice on Getting started, deleting an invoice line in review.

## Start again

`make demo-reset` empties the local demo database and loads the demo company again. It only works on the local database `matchdesk_dev` and refuses in production.
