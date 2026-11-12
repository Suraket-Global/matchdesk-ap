# CLAUDE.md — MatchDesk AP three-way match

Read [AGENTS.md](AGENTS.md) first. It is canonical for reading order, sources of truth, conventions, tenant safety, migrations, tests, Git hygiene and completion reporting. This file adds only what is specific to this product. Where the two differ, AGENTS.md wins.

Build milestone B1 (2026-11-11) added the foundation and the match core under `backend/`; B2 (2026-11-11) added sign-in, sessions, invitations, local mail (Mailpit) and S3 file storage (MinIO); B3 (2026-11-12) made every workflow work through the API on the local stack, without external accounts. See AGENTS.md for the state line and which commands exist. Everything else is still proposed.

## The question this product must answer

Will a distributor pay for a historical three-way match and supply invoices, purchase orders and receiving records? If a change does not help answer that, it probably does not belong (see R-21 in [verification-report-fixing.md](verification-report-fixing.md)).

## The buyer's workflow

- **Account:** a Lower Mainland wholesale distributor on QuickBooks Online Plus or Advanced with purchase orders enabled.
- **Clerk, daily:** receives supplier invoices, compares each with the purchase order and the packing slip, enters the bill, pays on the due date. In MatchDesk the clerk uploads invoices and the warehouse receiving file (or the QuickBooks item-receipt export where the receiver enters item receipts), confirms supplier-item aliases, fixes misread documents and resolves exceptions.
- **Controller, weekly:** approves unit conversions and larger waivers, sets tolerances, approves the back-test report, and uses its dollar findings with the owner and with suppliers.
- **First sale:** a back-test of last month for CAD 500, refunded if nothing is found (stated in the chat). The CAD 500 covers a 30-day pilot: the back-test plus live checking; the controller signs and pays; before the application exists the founder delivers the back-test by hand. The refund is decided by an objective criterion on one governing report version. All of this is in [Decision.md section 5](Decision.md#5-offer-channel-and-pilot) and is partly proposal.

## Highest-consequence error

The ranking of all failures is in [Decision.md section 1](Decision.md#1-proposed-decision): first, commercially, that target distributors have no independent receiving evidence; second, in the product, a false pass; third, a false finding. This section is about the product failures, which are what code can cause.

**A false pass:** a line shown as matched when the goods were not received or the price was wrong. The controller relies on it and an overpayment stands. The ways it can happen, each of which you must not introduce:

1. Checking one month in isolation. An invoice billed in September and re-billed in October passes unless earlier invoices and receipts on the same purchase order are counted (MH-06, AD-13).
2. Treating a missing receiving record as acceptable. `receipt_absent` is always an exception (MH-07). It may be a finding ("not received"); it is never a pass. It does not stop the price, ordered-quantity and duplicate checks, which need no receipt; skipping them would empty the report for exactly the accounts that lack receiving evidence.
3. Counting something that is not independent receiving evidence: QuickBooks' "billed against PO" quantity, a QuickBooks item receipt entered by accounts-payable staff or after the bill, or a supplier's packing slip with no receiver marks (AD-05, MH-03). QuickBooks Online does have item receipts (C1), but only as an export, not through the API. How QuickBooks produces its "Received" figure is still an assumption until T-1.1.1; the rule holds either way.
4. A wrong unit conversion on an alias (1 CS = 24 EA instead of 12). Conversions other than 1 need controller approval; a change re-matches everything that used the alias (MH-10).
5. Checking an invoice line alone instead of cumulatively across partial deliveries, earlier invoices and credit notes (MH-06, MH-09).
6. Trusting extracted numbers that do not add up. Documents failing the arithmetic gates go to a person (MH-05).
7. Letting a stale job overwrite a newer result, or letting arrival order change a result (R-01).

**A false finding** is the opposite error: reporting in dollars something already credited, returned, or counted twice. Credits, including QuickBooks vendor credits with no document, must be netted first; a duplicate's lines are left out of cumulative quantities; a possible duplicate or possible credit is reported as open, not as a finding (MH-08, MH-09).

## Sensitive data

| Data | Why it matters |
|---|---|
| QuickBooks refresh tokens | Open the account's entire books. Encrypted at application level; never logged; erased on disconnect |
| Supplier invoices, unit prices, purchase orders | The distributor's cost base. Tenant-isolated; never in logs, test fixtures or this repository |
| Reports and audit log | Evidence in supplier disputes; approved versions are immutable |
| User names and work emails | Personal information |

Documents are sent to an extraction provider. That must be covered by the pilot agreement and by no-training terms before any real document is processed.

## Prohibited shortcuts

- No tolerance, flag, default or bulk action that passes a line without independent receiving evidence (class A or B).
- No date filter on purchase-order history, receipts or earlier invoices when matching.
- No ordering by upload time anywhere in matching.
- No refund result computed from anything but the governing report's stored qualifying total; a waiver never lowers it.
- No model call that decides a match, a duplicate, a conversion, a finding or a dollar amount.
- No floats in money or quantity arithmetic.
- No query, job or file access outside `tenancy.session()` and `blobstore`.
- No write to QuickBooks.
- No overwriting of match results, resolutions or approved reports; supersede and keep history.
- No real customer data in fixtures, examples, screenshots or logs.
- No number without its label; no source cited that was not opened.
- No "done" for anything that has not run. Application tests stay `Not run` until executed.
- No new feature without an MH, R or operational-need reference.

## First verification checks when implementation begins

Run these, in this order, before building screens. IDs are defined in [execution-plan.md section 7](execution-plan.md#7-test-catalogue).

1. **T-1.1.1 fact sheet.** Confirm in a QuickBooks sandbox what the API returns for purchase-order lines, bill lines linked to them, vendor credits, the scopes on offer and the call limits. Replace every "unverified" QuickBooks statement in Decision.md and TRD.md with what was observed.
2. **UT-03, UT-23, UT-30, UT-31, IT-24.** A line with no counting receipt is `receipt_absent` under every tolerance setting; QuickBooks quantities and supplier-only slips do not count; the database refuses a matched row with zero receipt lines.
3. **UT-12, UT-13, UT-15.** History before the test month: an earlier invoice is counted, an earlier receipt is counted, and missing history blocks a pass.
4. **UT-01, UT-02, UT-06, UT-22, PT-01.** Partial deliveries pass cumulatively; over-invoicing is caught; a credit note clears the exception; a duplicate is reported once; arrival order does not change the result.
5. **UT-16, UT-17, IT-17.** "Not received" is a finding where the log covers the order; the refund result is right for each fixture.
6. **IT-01, IT-02, IT-03, IT-29.** No cross-tenant read, write, job or file access; the operator sees nothing without a grant.
7. **UT-08 and HR-01.** Arithmetic gates route bad extractions to review; the evaluation set meets its thresholds.
8. **IT-05, IT-06, IT-07.** Stale events change nothing; late completions reconcile; a batch's states sum to its file count and a retry touches only failures.
9. **OPS-04.** One proposed start command brings up every service with passing readiness checks.

## Vocabulary

Use the terms in [design.md section 9](design.md#9-vocabulary). In particular: "invoice" for the supplier's document, "QuickBooks bill" for the ledger record, "receiving record" for warehouse evidence, "receipt absent" for its absence, "receiving evidence" only for class A and class B, "not received" where the log covers the order and shows nothing, "finding" for a discrepancy the rules raised and no evidence removed (the controller's confirmation is a separate fact), and "unverified" for what could not be checked.
