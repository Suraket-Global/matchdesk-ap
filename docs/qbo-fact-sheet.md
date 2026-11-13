# QuickBooks Online API fact sheet (T-1.1.1)

Observed on **2026-11-13** in an Intuit sandbox company, through MatchDesk's own read-only client (`make qbo-capture`; the sanitised responses are in `backend/fixtures/qbo/sandbox/`). Nothing was written to QuickBooks. Every request was a GET to the query or CompanyInfo endpoint, except Intuit's OAuth token exchange and one refresh. Anything this sheet does not state as observed is still **unverified**.

## 1. What was read

| Item | Observed |
|---|---|
| Company | "Sandbox Company US 1499": Intuit's invented US sample company (`Country` US, currency USD, time zone America/Los_Angeles) |
| API host and version | `https://sandbox-quickbooks.api.intuit.com/v3/company/{realmId}/query`, `minorversion=75` on every request; every read answered 200. Whether 75 is the lowest version Intuit still serves was not tested |
| Scope | Only `com.intuit.quickbooks.accounting` was requested. The lead reported the consent screen as "Connecting MatchDesk to Sandbox Company US 1499". Intuit's token answer carried no `scope` field (S-04 showed no permission after connecting), so MatchDesk now records the requested scope. No read-only scope was offered or tested, so TRD 8.6 still treats the token as able to change the books |
| Tokens | Access token valid 1 hour. Refresh token about 100 days (`x_refresh_token_expires_in`). One real refresh succeeded on 2026-11-13 |
| Records | Vendor 26, Item 18, PurchaseOrder 3, Bill 15, VendorCredit **0** (from `select count(*)`) |

## 2. Shapes

**Purchase order** (`1002` Open, `1003` Closed, `1004` Closed; all dated 2026-10-16 to 2026-10-18):

- **Header fields:** `Id`, `DocNumber`, `TxnDate`, `POStatus` (`Open`, `Closed`), `TotalAmt`, `VendorRef`, `CurrencyRef`, `APAccountRef`, `ShipAddr`, `VendorAddr`, `EmailStatus`, `CustomField`, `LinkedTxn`, `SyncToken`, `MetaData`.
- **Line fields:** `Id`, `LineNum`, `Description`, `Amount`, `DetailType` (only `ItemBasedExpenseLineDetail` seen), `CustomExtensions`. The detail holds `ItemRef`, `Qty`, `UnitPrice`, `TaxCodeRef` (`NON`), `BillableStatus` and sometimes `CustomerRef`.
- **No received or billed quantity is exposed** on a purchase order or its lines. There is no `UOMRef` and no line-level `LinkedTxn`.
- **The link to a bill exists only on the PO header:** `LinkedTxn` `{"TxnId": "126", "TxnType": "Bill"}` on PO 1004. PO 1003 is linked to a `Purchase` (an expense), not a bill.

**Bill** (15):

- **Fields:** `Id`, `TxnDate`, `DueDate`, `TotalAmt`, `Balance`, `VendorRef`, `CurrencyRef`, `APAccountRef`, `SalesTermRef`, `PrivateNote`, `LinkedTxn`, `Line`.
- **None of the 15 sample bills has a `DocNumber`.**
- **Line detail types:** `ItemBasedExpenseLineDetail` (`ItemRef`, `Qty`, `UnitPrice`, `TaxCodeRef`) and `AccountBasedExpenseLineDetail` (`AccountRef`).
- **Header `LinkedTxn` types:** `BillPaymentCheck` and `ReimburseCharge`. The only line `LinkedTxn` type is `ReimburseCharge`.
- **No bill or bill line points back to a purchase order.** Bill 126 repeats PO 1004's items and quantities, but its own `LinkedTxn` is empty.

**Vendor credit:** none in the sample company. Its shape is unverified.

**Item:** `Name`, `Type`, `Active`, `UnitPrice`, `PurchaseCost`, `PurchaseDesc`, `QtyOnHand`, `TrackQtyOnHand`, account references. There is no `Sku` and no unit of measure.

**Vendor:** `DisplayName`, `CompanyName`, `Active`, `CurrencyRef`, `Balance`, `AcctNum`, `Vendor1099`, `V4IDPseudonym`, contact fields.

**Item receipts:** one probe on 2026-11-13, `select count(*) from ItemReceipt`, answered 400 "QueryValidationError: invalid context declaration: ItemReceipt". This matches SRC-16. The product never queries it (AGENTS.md section 3).

## 3. Paging, filters and limits

- `STARTPOSITION` / `MAXRESULTS` paging works, and `orderby Id` gives a stable numeric order across pages (pages 1–5 and 6–10 of Bill did not overlap).
- In a page, `QueryResponse.totalCount` is the number of rows **in that page**. Only `select count(*)` gives the total.
- An empty result is `{"QueryResponse": {}}`, with no entity key.
- These filters were accepted:
  - `DocNumber in (...)` and `TxnDate >= / <=` on PurchaseOrder;
  - `VendorRef in (...)` on Bill and VendorCredit;
  - `Active in (true, false)` on Vendor and Item;
  - a quote escaped as `\'`.
- **Limits:** no response carried a header naming a rate, limit, retry or throttle. The only response headers were `content-type`, `date`, `intuit_tid` and `x-request-id`; the last two were removed from the fixtures. No 429 was seen. Call limits and CorePlus usage per account remain **unmeasured** (TRD 11).

## 4. Assumptions: which held

| Assumption (recorded fixtures, Decision.md, TRD.md) | Result |
|---|---|
| PO lines carry item, quantity, unit price, amount, line number | **Holds** |
| Bill lines link to PO lines (`LinkedTxn` `PurchaseOrder` with `TxnLineId`) | **Not observed.** Only the PO names its bill, on the header. The sync now attributes a bill line to a PO line when exactly one open line of the naming PO has the same item. Otherwise the line stays unattributed, and matching treats that PO's history as unknown before the bill (`history_incomplete`, TRD 8.5) |
| QuickBooks exposes a received or billed quantity per PO line | **Not exposed** on the API. AD-05 is unchanged: nothing from QuickBooks counts as a receipt |
| Lines have a unit of measure (`UOMRef`), items a SKU | **Not observed** in this company (the US sample has neither) |
| Bills carry the supplier's invoice number in `DocNumber` | **Not observed** in the sample bills, so duplicate checks against QuickBooks bills by number find nothing here |
| Vendor credits as in the recorded fixtures | **Unverified:** the sandbox has none |
| Query paging with `STARTPOSITION` / `MAXRESULTS` | **Holds**, with `orderby Id` added |
| No item-receipt entity in the API | **Holds** |
| Canadian company: CAD, GST/HST tax codes | **Unverified.** The sandbox is US (USD, tax code `NON`). The sync does not yet read `CurrencyRef`, so a USD company's amounts are stored beside a CAD tenant without a check (open item B11-1 in verification-report-fixing.md) |

## 5. What the owner could add by hand in the sandbox (no MatchDesk writes)

1. A **Canada** sandbox company (developer portal, Sandbox, add company, Canada), to observe CAD amounts and GST/HST tax codes.
2. A purchase order with three lines, two of them the same item, then a bill made from it with **Add to bill** for part of the quantity, and a second partial bill. This shows whether a bill made from a PO carries a line-level `LinkedTxn`.
3. A bill with a **Bill no.** (the supplier's invoice number).
4. A **vendor credit** with item lines for a vendor that has a purchase order.
5. An item with a **SKU**, and, on Plus or Advanced with units of measure turned on, a PO line with a unit.
6. An **inactive vendor** with an open purchase order.

After any of these, run `make qbo-capture ARGS="--fixtures fixtures/qbo/sandbox"` and update this sheet.
