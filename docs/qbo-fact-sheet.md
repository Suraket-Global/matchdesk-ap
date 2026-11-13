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
| Canadian company: CAD, GST/HST tax codes | **Observed 2026-11-13/14** in "Sandbox Company CA b867" (section 6; fixtures in `backend/fixtures/qbo/sandbox-ca/`). Multicurrency is on: purchase orders and bills carry `CurrencyRef` (CAD and HKD seen, none in USD) and `ExchangeRate` (1 for CAD). Every purchase order and bill carries `GlobalTaxCalculation: TaxExcluded` and `TxnTaxDetail` (`TotalTax`, `TaxLine` with `TaxRateRef`, `TaxPercent`, `NetAmountTaxable`); CAD documents show 13 % (Ontario HST), HKD documents 0 %. Line `Amount` = `Qty` × `UnitPrice` **before tax**; the tax is only in `TxnTaxDetail` and `TotalAmt` (PO 1003: lines 262.50, tax 34.13, total 296.63). Line `TaxCodeRef` is an id (`5`, `2`), not `NON` as in the US company. MatchDesk compares prices before tax, so these amounts are used as read; a document marked `TaxInclusive` (not observed) is not stored and S-04 names it [default the founder may revisit]. The US company sends no `GlobalTaxCalculation`, `TxnTaxDetail` or `ExchangeRate` |
| A PO closed by something other than a bill | **Observed:** PO 1003's `LinkedTxn` names a `Purchase` (an expense), which MatchDesk does not read. **Default (founder may revisit):** a PO whose `LinkedTxn` names any transaction type other than a bill, or a bill MatchDesk does not hold, has unknown history. Every line on it is `history_incomplete` and never passes, and S-10 gives the reason ("QuickBooks links this purchase order to Purchase 115, which MatchDesk does not read") |

## 5. What the owner could add by hand in the sandbox (no MatchDesk writes)

1. ~~A **Canada** sandbox company~~: done in B13 (section 6). Still open there: a vendor credit, a document with tax included, PST/QST rates.
2. A purchase order with three lines, two of them the same item, then a bill made from it with **Add to bill** for part of the quantity, and a second partial bill. This shows whether a bill made from a PO carries a line-level `LinkedTxn`.
3. A bill with a **Bill no.** (the supplier's invoice number).
4. A **vendor credit** with item lines for a vendor that has a purchase order.
5. An item with a **SKU**, and, on Plus or Advanced with units of measure turned on, a PO line with a unit.
6. An **inactive vendor** with an open purchase order.

After any of these, run `make qbo-capture ARGS="--fixtures fixtures/qbo/sandbox"` and update this sheet.

## 6. Canada company: captured

**Done 2026-11-13/14 (B13).** The lead created "Sandbox Company CA b867" (Canada, QuickBooks Online Plus, Ontario address) and connected it to "Sandbox Distributor CA (Intuit sandbox)" through the real OAuth flow. Then, through the product's own read-only paths only:

- `make qbo-capture ARGS="--tenant 'Sandbox Distributor CA (Intuit sandbox)'"`: 11 reads, all 200. Counts: Vendor 36, Item 26, PurchaseOrder 5, Bill 4, VendorCredit **0**. The sanitised answers were read before they were copied to `backend/fixtures/qbo/sandbox-ca/` (realm, request IDs and e-mail addresses removed; the realm ID was checked absent).
- **Read now** on S-04 for 2026-04-01 to 2026-09-30 (`request_sync`, the worker's `execute_sync`, `IntuitQboReader`): succeeded with 2 PurchaseOrder, 1 Bill, 27 Item, 37 Vendor, 0 VendorCredit, and "3 documents in HKD skipped: this account is in CAD". Nothing in USD was skipped; the currency guard left out only the three HKD purchase orders, and their bills were not asked for (bills are read for the vendors of the stored purchase orders).

What the Canadian company showed, beyond the "Canadian company" row of section 4:

| Item | Observed |
|---|---|
| Purchase orders | 1001, 1002, 1005 in HKD (exchange rate about 0.135); 1003 and 1004 in CAD, both `Closed`, both naming Bill 97 in their own `LinkedTxn`. PO 1004 line 2 (25 × 4.00) was never billed although the PO is closed |
| Bills | No `DocNumber` on any bill (as in the US company). Bill 97 (CAD, 508.51 = 450.00 + 58.51 HST) holds lines from two purchase orders; its lines carry an empty `LinkedTxn`, so the link is on the PO header only, as in the US. The sync attributed each line by item to PO 1003 line 1 and PO 1004 line 1. Bill 98 is account-based (no item) and from a vendor with no purchase order. Bills 19 and 20 (HKD) are linked to `BillPaymentCheck` payments |
| Items | `PurchaseTaxCodeRef`, `PurchaseTaxIncluded`, `SalesTaxIncluded`, `Sku` present on items |
| Vendors | Canadian fields `T4AEligible`, `T5018Eligible`, `TaxIdentifier`; `CurrencyRef` per vendor |
| Not seen | Vendor credits, a `TaxInclusive` document, PST/QST or GST-only rates, units of measure |

Regression tests over the recorded answers: `backend/tests/integration/test_b13_canada.py`.

To read the company again: `make sandbox-up`, sign in as `controller.sandbox-ca@example.invalid` on http://localhost:5173, **Settings > QuickBooks > Read now**; `make qbo-capture ARGS="--tenant 'Sandbox Distributor CA (Intuit sandbox)'"` records it again. Since B13 `make demo-reset` keeps both sandbox accounts and their connections.
