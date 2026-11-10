# Decision — MatchDesk AP three-way match

**Question this repository exists to answer:** will a distributor pay for a historical three-way match and supply the invoices, purchase orders and receiving records it needs? An absent receipt is an exception, never a pass. Partial deliveries, credit notes and duplicate invoices must be handled.

Status of this document: planning only. No customer has been interviewed and no application exists. Willingness to pay is unproven.

## 0. How numbers are labelled

Every number in this repository carries one of three labels.

| Label | Meaning |
|---|---|
| **[chat]** | Stated in the portfolio owner's earlier discussion (recorded in the decision brief). |
| **[source: SRC-nn]** | Read by the author at a named source listed in [section 13](#13-sources-and-assumptions). |
| **[assumption]** | Everything else: unit-economics inputs produced by the site model, figures from the unverified research record, and the author's own proposals. An assumption is never a finding. |

Results calculated from assumptions are themselves assumptions. Currency is CAD throughout unless a line says otherwise. The only foreign-exchange conversion used is 1 USD = 1.38 CAD, direction USD to CAD, a site-model scenario value **[assumption]** with no sourced rate or rate date; it is used only to compare competitor list prices and one cost sensitivity.

## 1. Proposed decision

**Test, do not build yet.** Run Phase 0 of [execution-plan.md](execution-plan.md): a hand-run back-test on real records and paid back-test sales. Build the application only if the gates in [section 9](#9-stop-rule) pass. The chat's verdict was "test" with medium evidence confidence **[chat]**.

The reason for the order: the two facts that decide the product cannot be learned by writing code.

1. Whether distributors on QuickBooks Online hold receiving records that are independent of the supplier invoice.
2. Whether a controller will pay CAD 500 **[chat]** to have last month checked.

**Ranked risks, stated once.** Other documents refer to this ranking.

| Rank | Failure | Kind | Why it ranks here |
|---|---|---|---|
| 1 | Target distributors hold no receiving evidence independent of the invoice | Commercial | If true there is no three-way product to sell; nothing else matters |
| 2 | A false pass: a line shown as matched when goods were not received or the price was wrong | Product | The controller relies on it and an overpayment stands. Its causes, in the order the plan guards against them: missing open-PO history, a wrong unit conversion, receiving evidence that is not independent, an absent receipt treated as fine, extraction that does not add up, a stale job overwriting a newer result |
| 3 | A false finding: something already credited or explained is reported in dollars | Product | The controller sends it to a supplier and loses credibility |

**Known limit of the launch market.** On this plan's own ramp, reaching the 27 accounts that cover founder compensation takes 33 monthly cohorts of 300 distinct prospects, 9,900 in all **[assumption]** ([section 8](#8-funnel-recomputed-from-distinct-reachable-prospects)). No source gives the number of qualifying Lower Mainland distributors; it is very likely smaller. If T-0.1.1 counts fewer than 9,900, cold outreach in the launch market alone cannot reach founder-paid break-even at the assumed rates, and the plan then depends on referral partners or on expansion that this repository does not plan.

## 2. Market, people and current practice

| Item | Decision or record | Label |
|---|---|---|
| Launch market | Lower Mainland (Vancouver, Burnaby, Richmond, Delta, Surrey) food, building-supply and industrial wholesale distributors on QuickBooks Online with purchase orders enabled | [chat] for "Vancouver" and QuickBooks Online; niche wording [assumption] from the research record |
| Ideal account | Revenue CAD 5–50 million, 20–150 employees, 1–4 accounts-payable staff, 200–1,500 supplier invoices per month | [assumption] (research record, not measured) |
| Daily user | Accounts-payable clerk who compares invoice, purchase order and packing slip | [assumption] |
| Buyer | Controller or finance manager | [chat] |
| Budget owner | Owner signs off purchases under about CAD 10,000 a year | [assumption] (research record) |
| Who signs and pays for the pilot | **Not decided in chat.** Proposal: the controller signs the one-page pilot agreement and pays the CAD 500 from the finance budget; where the controller has no authority to sign, the owner signs. Discovery asks "who signs a CAD 500 pilot" before the offer is made, and the funnel log records the signatory | [assumption] (author proposal) |
| Qualification rule | Purchase orders for at least 70 percent of purchases, 200 or more supplier invoices a month, QuickBooks Online Plus or Advanced, receiving data somewhere digital. This is what "qualified" means in the funnel | [assumption] (research record) |
| Current workaround | Clerk opens invoice, purchase order and packing slip side by side and ticks lines; many firms check only totals or invoices above a dollar threshold | [assumption] (research record) |
| Buying triggers | A discovered duplicate or overpayment; clerk leaves; year-end audit finding; volume beyond one clerk | [assumption] |

## 3. Competitor gap: what was read today and what was not

All vendor pages were opened on 2026-11-10. These are **vendor-advertised features and list prices**. None is a measured customer outcome, and no customer of any competitor was consulted.

| Competitor | What the vendor page states | Status | Effect on the plan |
|---|---|---|---|
| BILL | Accounts-payable plans at $49, $65 and $89 per user per month and a custom-priced Enterprise plan. "2-way matching" is listed from Corporate. "Sync purchasing orders and automatic 2 and 3-way matching" is listed on Enterprise only, with the footnote "Features vary by accounting software". Plan currency is not named on the page | [source: SRC-01] | Confirms the brief: three-way match is gated to the custom tier |
| BILL in Canada | The brief says Canadian payment support is limited. The pricing page lists Canadian withdrawal fees and states no limitation | **unverified, no source consulted** for the limitation | Do not use in sales material |
| Precoro | Core from $499 per month billed annually, includes "2- and 3-way match" and "QuickBooks Online / Xero". Automation from $999 per month. A separate AP Module from $499 per month is also listed. The page says it accepts US dollars, pounds and euros | [source: SRC-02] | Confirms the brief. At the scenario rate, 499 × 1.38 = CAD 688.62 per month [assumption] |
| ProcurementExpress | Basic $415 per month, "manage up to $10k per month", single organisation, QuickBooks integration listed. Better $900. Best $2,550. The term "three-way matching" does not appear; "Scan & Match" appears only on Best | [source: SRC-03] | **Changes the brief.** The brief's secondary item said the $415 plan includes three-way matching. The vendor page does not support that. The lowest verified price for three-way match with QuickBooks Online is Precoro at $499, not $415 |
| Stampli | No price published. "Semi-automated 2-3 way matching included". QuickBooks Online, QuickBooks Desktop, Sage 100 and Sage Intacct listed; Sage 50 not listed | [source: SRC-04] | Confirms the brief |
| Procurify | No price published; quotes are custom. Three-way matching is not named. The brief's "about USD 1,000 per month" came from a review site | [source: SRC-05] for "no public price"; the USD 1,000 figure is **unverified, no source consulted** | Drop the USD 1,000 figure from any buyer-facing claim |

**Gap as it stands after verification.** A distributor that keeps purchasing in QuickBooks Online and wants line-level three-way match without adopting a procurement suite has, among the vendors read, a verified entry price of USD 499 per month on annual billing (Precoro) or a custom quote (BILL Enterprise, Stampli, Procurify). MatchDesk's proposed CAD 249 and CAD 449 tiers **[chat]** sit below CAD 688.62 **[assumption, FX]**. The gap type is "overpriced incumbents" **[assumption]**; price is the only verified part of it.

### The assumption that matters most: QuickBooks Online receiving

| Claim | Evidence | Status |
|---|---|---|
| QuickBooks Online Plus and Advanced include purchase orders; lower plans do not. Regular prices CAD 110 and CAD 220 per month | Intuit Canada pricing page | [source: SRC-06] |
| QuickBooks Online has no item-receipt transaction. A partial delivery is recorded by adding the purchase order to a bill, expense or cheque and editing the quantity; the purchase order shows a "Received" column and closes when the full quantity has been added | Two answers on Intuit's own community site, both dated 2020; one author is not identified as Intuit staff | [source: SRC-07], weak: forum answers, six years old |
| QuickBooks Online lets several bills, expenses and cheques be linked to one purchase order; a "Received" column shows quantity to date and a "Closed" tick appears when all is received. No item-receipt transaction is mentioned | Intuit Australia product post (page metadata dates 2017-07-19 and 2023-07-05) | [source: SRC-11] |
| "QuickBooks Online automatically closes purchase orders when all quantities are added to bills, expenses, or checks" | Reply by a QuickBooks Team member dated 2023-08-02 on Intuit's community site | [source: SRC-12] |
| The official help article on adding a purchase order to a bill | Two URL variants returned HTTP 404 | **unverified, no source consulted** |
| QuickBooks Online Accounting API: PurchaseOrder entity fields, absence of an ItemReceipt entity, rate limits | developer.intuit.com returned only a page title to the author's tool (script-rendered pages) | **unverified, no source consulted** |
| Intuit App Partner Program fees and metered API calls | Official FAQ page not readable; third-party articles seen in search results mention a free tier with a monthly cap on metered calls and paid tiers from USD 300 per month | **unverified, no source consulted** (third-party figures are not used as fact) |

**Consequence.** Four Intuit-hosted pages agree, and none is API documentation, so this stays an assumption until T-1.1.1: the "Received" quantity on a QuickBooks Online purchase order appears to be produced by entering the supplier's bill. If so it is not independent evidence that goods arrived, and comparing an invoice with it is a two-way match counted twice. Whatever T-1.1.1 finds, this plan makes a design decision (AD-05 in [TRD.md](TRD.md)) that does not depend on it:

- A receiving record counts only if it is **independent receiving evidence**, defined below.
- The QuickBooks "Received" quantity is shown as context. It never satisfies the receipt check. It is used on the invoiced side only, to detect earlier bills on the same purchase order ([section 5](#5-offer-channel-and-pilot), open-PO history).
- An account that can supply no independent receiving evidence gets a report that says so, every purchase-order line is an exception of type "receipt absent", and the account counts toward the stop rule.

**What counts as independent receiving evidence [assumption] (author proposal).**

| Class | What it is | Counts as a receipt? |
|---|---|---|
| A. Warehouse record | A receiving log, spreadsheet or inventory-system export written by the account's receiving staff when goods arrive | Yes |
| B. Receiver-attested delivery document | A supplier packing slip, delivery note or bill of lading that carries a receiver's signature or count marks and a date, made by someone at the account other than the person resolving the exception | Yes, once the clerk has recorded for each slip that the marks are present and who signed |
| C. Supplier document only | A packing slip or shipping notice with no receiver marks | **No.** It says what the supplier claims to have shipped, the same party as the invoice. It is stored and shown as context; the line stays "receipt absent" with the sub-reason "supplier slip only" |

Two further controls: the controller attests once per pilot which class the account's evidence belongs to and who produces it; and receiving evidence added *after* an exception was raised on that purchase-order line counts only when the controller approves it, so the clerk who clears exceptions cannot also create the receipt that clears them. The report states receipt coverage separately for class A and class B and counts lines with class C only.

The brief already listed "QuickBooks Online has weak receiving records" as a technical risk **[assumption]**; the pages read today make it the first-ranked risk of [section 1](#1-proposed-decision). Task T-1.1.1 confirms it in a QuickBooks sandbox before any build.

## 4. Strongest evidence and strongest counterargument

**Strongest supporting evidence.** Verified list prices show that three-way match is sold at USD 499 per month and up or by custom quote among the vendors read ([SRC-01] to [SRC-05]). Nothing else in this plan is evidence; the rest is assumption.

**Strongest counterargument.** The customers this product targets may not record receiving at all, or only inside QuickBooks through the bill. Then the product can deliver only a two-way match plus duplicate detection, which BILL lists from its Corporate plan at $89 per user per month [source: SRC-01]. A distributor with two accounts-payable users would pay $178 per month there, 178 × 1.38 = CAD 245.64 **[assumption, FX]**, about the same as MatchDesk's Starter tier. A second counterargument from the research record: distributors on thin margins may accept current leakage **[assumption]**.

**Competition risk carried from the research record [assumption].** BILL, Stampli and AI accounts-payable startups can lower the tier at which three-way match is offered. Price is the only verified part of the gap, so one pricing change by BILL removes it. The research record also describes Precoro's gap as "requires moving purchasing into Precoro" and BILL's and Procurify's as suite-level products; these are the research record's characterisations, not something read on a vendor page, and no customer confirmed them.

**Market limit.** See "Known limit of the launch market" in [section 1](#1-proposed-decision).

## 5. Offer, channel and pilot

| Item | Record | Label |
|---|---|---|
| Offer, as stated | Chat, translated: "last month's back-test CAD 500, refund if nothing is found" | [chat] |
| What the CAD 500 covers | The research record says: "Paid 30-day pilot at CAD 500 that processes last month's invoices and shows the mismatches found" and "30 days, CAD 500, back-test of last month's invoices plus live processing". So the CAD 500 buys the whole 30-day pilot: the back-test report and, where the application exists, live checking of new invoices for the rest of the 30 days. Nothing else is charged during the pilot. Subscription billing starts on day 31 only if the controller subscribes | [assumption] (research record); the day-31 start is an author proposal |
| How a back-test sold in Phase 0 is delivered | Before the application exists, the founder runs it by hand in a spreadsheet with the rule table of TRD section 8.5 (12–20 hours each, the estimate of T-0.1.4), on the month before the sale, and delivers the report within 15 business days of receiving the records. The live-checking part is owed later: when the application is released the account gets 30 days of it at no further charge before any subscription starts. The pilot agreement says this in plain words | [assumption] (author proposal) |
| Pilot duration | 30 days: the back-test plus live processing of new invoices | [assumption] (research record) |
| What "found" means | **Not decided in chat.** The proposal is in [section 5.1](#51-refund-criterion-proposal) | [assumption] (author proposal) |
| Sample inputs the account must supply | (1) Read access to its QuickBooks Online company for purchase orders, vendors, items, bills and vendor credits. (2) Supplier invoice and credit-note PDFs dated in the test month. (3) **Open-PO history:** for every purchase order that a test-month document refers to, all earlier invoices, credit notes and receiving records on that purchase order, whatever their date. Earlier invoiced quantity is taken from QuickBooks bills linked to the purchase order where they carry line quantities; otherwise the earlier invoice PDFs are needed. (4) Independent receiving evidence (section 3) for those purchase orders, for any date. A one-month slice alone is not enough: an invoice billed in September and re-billed in October under another number would pass | [assumption] (author proposal derived from the pilot question) |
| Subscription tiers | CAD 249, 449 and 799 per month | [chat] |
| Tier limits and overage | Starter 300, Pro 800, Business 2,000 invoices per month; CAD 0.60 per invoice above the limit; 15% discount for annual billing. This plan counts credit notes toward the limit as well, because each is a billable unit (section 6) | [assumption] (research record; the credit-note reading is the author's) |
| Other prices in the research record | Launch price CAD 299, minimum CAD 149, maximum CAD 999. The research record does not say how the CAD 299 launch price relates to the CAD 249 Starter tier; not reconciled, and not used in any calculation here | [assumption] (research record) |
| Primary channel | Direct outreach to controllers at Lower Mainland distributors, leading with the paid back-test | [assumption] |
| Backup channel | Referrals from fractional controllers and QuickBooks consultants; CAD 300 credit per referred distributor that goes live | [assumption] |
| Prospect sources | BC Food and Beverage; building-supply dealer lists; QuickBooks ProAdvisor firms | [chat] |
| Further prospect sources | Canadian Association of Importers and Exporters; Western Retail Lumber Association; Canadian Company Capabilities database, NAICS 41, BC; LinkedIn Sales Navigator | [assumption] (research record; none of these lists was opened) |
| Lead cost | About CAD 350 per 100 prospects, so CAD 3.50 per prospect | [assumption] |
| Sales cycle | 35 days | [chat] |
| First step for the first customer | Offer the refundable back-test to 10 distributors met through warm introductions | [assumption] |
| Later steps in the research record | Use the first back-test's dollar result as the outreach hook; sign two fractional-controller firms as referral partners for the first ten customers | [assumption] (research record) |
| Founder time and budget for the first 30 days | 80 founder hours; CAD 1,200 go-to-market budget; CAD 2,000 cash in total | [assumption] (research record) |
| Research record's week-4 gate | "CAD 750 MRR and one documented overpayment found" by day 30. CAD 750 of monthly recurring revenue needs two or three subscriptions inside 30 days, which the 35-day sales cycle plus a 30-day pilot cannot produce. Kept on record; this plan does not use it as a gate. "One documented overpayment" is kept as clause 5 of the stop rule in another form | [assumption] (research record) |
| Compliance expectation | Canadian privacy law applies; "SOC 2 will be asked for by larger buyers later" | [assumption] (research record; no source consulted) |

### 5.1 Refund criterion (proposal)

The chat's term is "refund if nothing is found" **[chat]**. It does not say what "found" means, who decides, or on which version of the report. Everything below is an author proposal **[assumption]** for the founder to accept, change or reject before T-0.2.1. It is written so that neither side can change the outcome alone.

1. **What counts.** A *qualifying discrepancy* is an exception that MatchDesk's rule table raised on the documents the account supplied, of one of these types: invoiced above received, invoiced above ordered, price variance beyond tolerance, duplicate, unmatched charge, or receipt absent where receiving evidence covers the purchase order and shows nothing ("invoiced, not received"; rule in TRD section 8.5). A receipt-absent line outside that coverage also qualifies once the controller confirms in the product that the goods were not received.
2. **What removes one.** Only evidence: a corrected source document, a credit note, or a receiving record that passes the independence rules of section 3. A waiver, or the controller declining to confirm, does not remove it. The buyer's confirmation is not required.
3. **What does not count, and is shown anyway.** Receipt-absent lines where the account has no receiving evidence covering that purchase order and the controller has not confirmed non-delivery (unverified, neither found nor cleared; their count and dollar total are printed beside the refund calculation so they are never silently left out); possible duplicates not yet confirmed either way; lines waiting on extraction review or an alias.
4. **Threshold.** The fee is refunded unless qualifying discrepancies total at least **CAD 500**, the fee itself and the research record's invalidation threshold. A CAD 0.01 variance does not defeat the refund. The founder may prefer "any amount above CAD 0", which is closer to the chat's words and refunds less often.
5. **Governing version.** The decision is made once, on the report version that is current at the end of the review window: 10 business days after the first draft with no extraction review outstanding is delivered. That version is recorded as the governing report. Later versions do not change money already refunded or kept.
6. **Who records it.** The operator, from the governing report's stored figure; both controller and operator see the calculation.

**Accepted residual risk.** An account can withhold receiving evidence so that discrepancies fall under point 3 and claim the refund. That account is also a stop-rule data point (no usable receiving data), so the refund is the price of learning it. A founder who does not accept this should make supplying receiving evidence a condition of the refund.

## 6. One paying account, one billable unit

Neither was decided in chat. Both definitions below are author proposals **[assumption]**.

- **One paying account** = one distributor legal entity with one connected QuickBooks Online company, under one subscription or one pilot agreement. A group with two QuickBooks companies is two accounts. Users are not billed; the brief's rationale is "no per-user fee" **[assumption]**.
- **One billable unit** = one supplier document (invoice or credit note) that MatchDesk extracts and runs through matching for that account, counted once in the calendar month (Pacific time) in which it is first extracted. A PDF holding three invoices is three units. A file rejected as a byte-identical re-upload is not a unit. A document flagged as a possible duplicate is a unit, because the work was done. Packing slips and receiving files are not units; their extraction cost is assumed to sit inside the CAD 18 extraction line and is a missing input. Units are counted in `usage_events` ([schema.md](schema.md)).

### Reconciling the three prices

The chat gave three tier prices, one pilot price and, through the site model, CAD 380 of monthly revenue per account. They were not reconciled in chat.

| Element | Treatment | Arithmetic |
|---|---|---|
| CAD 380 monthly revenue per account [assumption] | Kept as the model input. It equals a tier mix of 52% Starter, 38% Pro, 10% Business with monthly billing and no overage. The mix is an author assumption chosen to reproduce 380; no evidence supports it | 0.52 × 249 + 0.38 × 449 + 0.10 × 799 = 129.48 + 170.62 + 79.90 = **380.00** |
| CAD 500 pilot fee [chat] | One-off. Covers the 30-day pilot (back-test plus live checking, section 5); subscription revenue starts on day 31. Not part of the 380. It offsets acquisition cost; the base case below ignores it because the refund rate is unknown | Net of card fee: 500 − (0.029 × 500 + 0.30) = 500 − 14.80 = **485.20**. Less one pilot month of variable cost excluding card fee (18 + 8 + 2 + 2 + 40 + 5 = 75.00 [assumption]): 485.20 − 75.00 = **410.20**, before the founder's 12–20 hours when run by hand |
| Annual discount 15% [assumption] | Not in the base case. Each account that chooses annual billing lowers its monthly revenue by 15% | Starter 249 × 0.85 = 211.65; Pro 449 × 0.85 = 381.65; Business 799 × 0.85 = 679.15 per month |
| Overage CAD 0.60 [assumption] | Not in the base case | Starter at 600 invoices: 249 + (600 − 300) × 0.60 = 429.00 |

**Inconsistency the author could not remove.** The cost side of the model assumes 600 invoices per account per month **[assumption]**. An account with 600 invoices cannot sit on Starter without overage: it pays 429.00 with overage or 449 on Pro. So a 600-invoice average account implies revenue of at least 429, not 380. Conversely the 52/38/10 mix implies a lower volume: with assumed typical volumes of 250, 550 and 1,400 invoices, 0.52 × 250 + 0.38 × 550 + 0.10 × 1,400 = 479 invoices **[assumption]**. The base case keeps both brief values (revenue 380, extraction cost for 600 invoices), which is conservative. The real tier mix is a missing input that only signed accounts can supply.

## 7. Unit economics

All inputs are site-model assumptions **[assumption]** unless marked. The card-fee rate matches Stripe's published Canadian rate for domestic cards, 2.9% + CAD 0.30 [source: SRC-08].

### 7.1 Cost categories kept apart

| Category | Base-case value | Notes |
|---|---|---|
| Startup cost, cash | CAD 2,000 for the 30-day validation | [assumption] (research record). Whether the CAD 1,200 go-to-market budget sits inside the 2,000 is not decided in chat; treated as inside. The ramp in 7.5 also charges CAD 1,800 of acquisition spend in month 1, so month 1 counts outreach twice; this is deliberate and conservative |
| Startup cost, development time | 160 hours × CAD 100 = CAD 16,000 | [assumption]. Not cash if the founder builds. Do not add it to founder compensation for the same months; that would count the same hours twice. The task estimates in [execution-plan.md](execution-plan.md) come to more than 160 hours; see section 5 there |
| Monthly fixed cost, excluding founder | CAD 900 | [assumption]. Composition not decided in chat |
| Founder compensation | CAD 6,000 per month | [chat]: an assumption that the chat stated, not a measured cost |
| Variable cost per account per month | CAD 86.32 | See 7.2 |
| Initial acquisition cost | CAD 1,500 per new paying account | [assumption] |
| Churn-replacement cost | Monthly churn 2.5% × CAD 1,500 = CAD 37.50 per active account per month | [assumption] |

### 7.2 Gross profit per account per month (base case)

| Line | CAD |
|---|---|
| Revenue | 380.00 |
| Extraction (600 invoices × 0.03) | 18.00 |
| Third-party API | 0.00 |
| Hosting | 8.00 |
| Storage | 2.00 |
| Messaging | 2.00 |
| Support | 40.00 |
| Other | 5.00 |
| Card fee (0.029 × 380 + 0.30 = 11.02 + 0.30) | 11.32 |
| **Variable cost** (18 + 0 + 8 + 2 + 2 + 40 + 5 + 11.32) | **86.32** |
| **Gross profit** (380.00 − 86.32) | **293.68** |
| Gross margin (293.68 ÷ 380) | 77.3% |

The chat's "Margin 77%" **[chat]** reproduces.

### 7.3 Payback, lifetime value, break-even (base case)

| Result | Arithmetic | Value |
|---|---|---|
| Acquisition payback | 1,500 ÷ 293.68 | 5.11 months |
| Payback if one unrefunded back-test fee offsets acquisition | (1,500 − 485.20) ÷ 293.68 = 1,014.80 ÷ 293.68 | 3.46 months |
| Lifetime gross profit | 293.68 ÷ 0.025 | CAD 11,747 |
| Gross profit after churn replacement | 293.68 − 37.50 | CAD 256.18 per account per month |
| Break-even accounts, without founder, churn replaced | 900 ÷ 256.18 = 3.51, rounded up | **4** |
| Break-even accounts, with founder, churn replaced | (900 + 6,000) ÷ 256.18 = 26.93, rounded up | **27** |
| Break-even accounts, without founder, no acquisition spend at all | 900 ÷ 293.68 = 3.06, rounded up | 4 |
| Break-even accounts, with founder, no acquisition spend at all | 6,900 ÷ 293.68 = 23.49, rounded up | 24 |

The chat's "Break-even 4 (27)" **[chat]** reproduces.

**Sensitivity: QuickBooks developer programme fee.** If a paid Intuit partner tier at USD 300 per month proves necessary (unverified, see section 3), fixed cost rises by 300 × 1.38 = CAD 414 to CAD 1,314 **[assumption]**. Break-even becomes 1,314 ÷ 256.18 = 5.13, so 6 accounts without founder, and 7,314 ÷ 256.18 = 28.55, so 29 with founder.

### 7.4 Downside case

Five inputs change; the rest stay. All are assumptions.

| Input | Base | Downside | Why |
|---|---|---|---|
| Revenue per account | 380 | 249 | Every account takes Starter |
| Support cost per account | 40 | 60 | Supplier item maps keep needing attention |
| Acquisition cost | 1,500 | 3,000 | Half the conversion for the same outreach spend |
| Monthly churn | 2.5% | 4% | Value drops where receiving is absent |
| New paying accounts per month | 1.2 | 0.6 | See funnel, reading B |

| Result | Arithmetic | Value |
|---|---|---|
| Card fee | 0.029 × 249 + 0.30 = 7.22 + 0.30 | 7.52 |
| Variable cost | 18 + 0 + 8 + 2 + 2 + 60 + 5 + 7.52 | 102.52 |
| Gross profit | 249 − 102.52 | 146.48 (58.8%) |
| Payback | 3,000 ÷ 146.48 | 20.48 months |
| Lifetime gross profit | 146.48 ÷ 0.04 | CAD 3,662, which is 1.22 × acquisition cost |
| Gross profit after churn replacement | 146.48 − 0.04 × 3,000 = 146.48 − 120 | 26.48 |
| Break-even accounts, without founder | 900 ÷ 26.48 = 33.99, rounded up | 34 |
| Break-even accounts, with founder | 6,900 ÷ 26.48 = 260.57, rounded up | 261 |
| Largest account base the funnel can sustain | 0.6 ÷ 0.04 | 15 accounts |

In the downside the account base tops out at 15, below the 34 needed. The business does not break even at any horizon. This is the case the paid back-tests exist to rule out.

### 7.5 Cash required during the acquisition ramp

**Timeline the ramp must respect.** Subscriptions cannot start before the application exists.

| Months | What happens | Basis |
|---|---|---|
| 1–2 | Phase 0: census, outreach, back-tests sold and delivered by hand; Gate A at day 60 under the proposed stop rule | [execution-plan.md](execution-plan.md) Phase 0 |
| 3–5 or 3–6 | Build and release: 338–534 hours. At 140 productive hours per developer-month [assumption], 338 ÷ 140 = 2.4 months and 534 ÷ 140 = 3.8 months for one developer | execution-plan.md section 5 |
| 6 or 7 | First 30-day pilots on the application | 30-day pilot [assumption] |
| 7 or 8 | First subscription revenue | Day 31 of the pilot |

The base case takes **month 7** for the first subscription, which is the low build estimate with one developer. Month 8 is the high estimate. Month 6 needs two developers or the smaller 142–225 hour cut (225 ÷ 140 = 1.6 months). Both are shown as sensitivities.

**Who builds while the founder sells.** The ramp keeps outreach running every month. From month 3 that is 20–30 hours of outreach and calls plus 1.2 hand deliveries at 12–20 hours (14.4–24.0), so 34.4–54.0 hours a month, 25–39% of 140 **[assumption]** ([section 12.8](#128-first-30-60-and-90-days)). Month 7 therefore holds only if a developer other than the selling founder builds, or if outreach pauses during the build. For a founder who builds alone and keeps selling, productive build hours are 140 − 34.4 = 105.6 to 140 − 54.0 = 86.0 a month: 338 ÷ 105.6 = 3.2 months on the low estimate, which puts the first subscription in **month 8** (the month-8 row of the table below is then the base), and 534 ÷ 86.0 = 6.2 months on the high estimate, which puts it in month 11. Month 11 is not tabulated; by the rule under the table (2,700 and 8,700 per month of delay) it is four months after the base: −27,826 − 4 × 2,700 = CAD −38,626 without founder compensation and −188,841 − 4 × 8,700 = CAD −223,641 with it, and 27 accounts in month 43. How many developers there are is a missing input.

Rules used, all **[assumption]**:

- New paying accounts per month from the start month: 1.2 in the base case (the chat's funnel, section 8).
- Active accounts: `A(t) = A(t−1) × (1 − churn) + new(t)`. Gross profit is earned on `A(t)`.
- Acquisition spend is `new × acquisition cost` **every month from month 1**, including the months before any subscription can start: 1.2 × 1,500 = 1,800 (base) and 0.6 × 3,000 = 1,800 (downside). This is conservative; pausing outreach during the build would lower the trough and delay the ramp. The churn-replacement share is `A(t−1) × churn × acquisition cost`; the remainder is growth acquisition.
- Fixed cost 900 every month. Startup cash 2,000 in month 1, in addition to that month's 900 and 1,800 (section 7.1).
- Pilot fees are excluded (refund rate unknown). Founder time spent delivering Phase 0 back-tests by hand is inside founder compensation.

**Base case, first subscription in month 7, CAD**

| Month | New | Active | Gross profit | Fixed | Acquisition spend | of which churn replacement | Startup | Net without founder | Cumulative without founder | Net with founder | Cumulative with founder |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 0.00 | 0.00 | 900 | 1,800 | 0.00 | 2,000 | −4,700.00 | −4,700.00 | −10,700.00 | −10,700.00 |
| 2 | 0 | 0.00 | 0.00 | 900 | 1,800 | 0.00 | 0 | −2,700.00 | −7,400.00 | −8,700.00 | −19,400.00 |
| 3 | 0 | 0.00 | 0.00 | 900 | 1,800 | 0.00 | 0 | −2,700.00 | −10,100.00 | −8,700.00 | −28,100.00 |
| 4 | 0 | 0.00 | 0.00 | 900 | 1,800 | 0.00 | 0 | −2,700.00 | −12,800.00 | −8,700.00 | −36,800.00 |
| 5 | 0 | 0.00 | 0.00 | 900 | 1,800 | 0.00 | 0 | −2,700.00 | −15,500.00 | −8,700.00 | −45,500.00 |
| 6 | 0 | 0.00 | 0.00 | 900 | 1,800 | 0.00 | 0 | −2,700.00 | −18,200.00 | −8,700.00 | −54,200.00 |
| 7 | 1.2 | 1.20 | 352.42 | 900 | 1,800 | 0.00 | 0 | −2,347.58 | −20,547.58 | −8,347.58 | −62,547.58 |
| 8 | 1.2 | 2.37 | 696.02 | 900 | 1,800 | 45.00 | 0 | −2,003.98 | −22,551.56 | −8,003.98 | −70,551.56 |
| 9 | 1.2 | 3.51 | 1,031.04 | 900 | 1,800 | 88.88 | 0 | −1,668.96 | −24,220.53 | −7,668.96 | −78,220.53 |
| 10 | 1.2 | 4.62 | 1,357.68 | 900 | 1,800 | 131.65 | 0 | −1,342.32 | −25,562.85 | −7,342.32 | −85,562.85 |
| 11 | 1.2 | 5.71 | 1,676.15 | 900 | 1,800 | 173.36 | 0 | −1,023.85 | −26,586.70 | −7,023.85 | −92,586.70 |
| 12 | 1.2 | 6.76 | 1,986.66 | 900 | 1,800 | 214.03 | 0 | −713.34 | −27,300.03 | −6,713.34 | −99,300.03 |
| 13 | 1.2 | 7.80 | 2,289.41 | 900 | 1,800 | 253.68 | 0 | −410.59 | −27,710.62 | −6,410.59 | −105,710.62 |
| 14 | 1.2 | 8.80 | 2,584.59 | 900 | 1,800 | 292.34 | 0 | −115.41 | −27,826.03 | −6,115.41 | −111,826.03 |
| 15 | 1.2 | 9.78 | 2,872.39 | 900 | 1,800 | 330.03 | 0 | 172.39 | −27,653.63 | −5,827.61 | −117,653.63 |
| 16 | 1.2 | 10.74 | 3,153.00 | 900 | 1,800 | 366.78 | 0 | 453.00 | −27,200.63 | −5,547.00 | −123,200.63 |
| 17 | 1.2 | 11.67 | 3,426.59 | 900 | 1,800 | 402.61 | 0 | 726.59 | −26,474.04 | −5,273.41 | −128,474.04 |
| 18 | 1.2 | 12.58 | 3,693.34 | 900 | 1,800 | 437.54 | 0 | 993.34 | −25,480.70 | −5,006.66 | −133,480.70 |

Active accounts are shown to two decimals; gross profit is calculated on the unrounded value, so a cell may differ by a cent or two from a hand calculation on the rounded figure.

Reading the base case:

- **Without founder compensation**, the deepest cumulative cash position is **CAD −27,826** in month 14. Monthly cash turns positive in month 15, when active accounts first exceed (900 + 1,800) ÷ 293.68 = 9.19.
- **With founder compensation**, cumulative cash is CAD −133,481 at month 18 and keeps falling. Monthly cash turns positive when active accounts exceed (6,900 + 1,800) ÷ 293.68 = 29.62, which the recurrence reaches in month 44. The deepest position is about **CAD −188,841** in month 43.
- The 27-account break-even of section 7.3 (26.93 before rounding up) is reached in month 39 at 1.2 new accounts per month. The account base can never exceed 1.2 ÷ 0.025 = 48.
- At 2.0 new accounts per month (500 distinct prospects a month at the same rates) 27 accounts are reached in month 23.

| First subscription in | Deepest cash without founder | in month | Deepest cash with founder | in month | 27 accounts in month |
|---|---|---|---|---|---|
| Month 6 | −25,126 | 13 | −180,141 | 42 | 38 |
| **Month 7 (base)** | **−27,826** | **14** | **−188,841** | **43** | **39** |
| Month 8 | −30,526 | 15 | −197,541 | 44 | 40 |

Each month of delay adds 2,700 (fixed plus acquisition spend) to the trough without founder and 8,700 with founder.

**Excluded from the ramp: the cost of a separate developer.** The ramp charges CAD 6,000 a month of founder compensation and no developer cash. The month-7 base holds only if someone other than the selling founder builds (see "Who builds while the founder sells" above). If that developer is paid at the model's CAD 100 an hour **[assumption]**, the build costs 338 × 100 = CAD 33,800 to 534 × 100 = CAD 53,400 (execution-plan.md section 5), spent in months 3 to 6, before either trough. It adds to them in full:

| Case | Deepest cash without founder | Deepest cash with founder |
|---|---|---|
| Month 7 base, as tabulated (developer cost excluded) | −27,826 | −188,841 |
| Month 7, paid developer, low estimate (338 hours) | −27,826 − 33,800 = −61,626 | −188,841 − 33,800 = −222,641 |
| Month 8, paid developer, high estimate (534 hours) | −30,526 − 53,400 = −83,926 | −197,541 − 53,400 = −250,941 |

The developer cost alone is larger than the tabulated trough without founder compensation. A founder who builds alone pays no such cost but reaches the first subscription in month 8 or 11, with the troughs given above.

**Downside case, first subscription in month 7, CAD** (gross profit 146.48, churn 4%, 0.6 new accounts per month, acquisition spend 1,800 per month)

| Month | Active | Gross profit | Net without founder | Cumulative without founder | Cumulative with founder |
|---|---|---|---|---|---|
| 1 | 0.00 | 0.00 | −4,700.00 | −4,700.00 | −10,700.00 |
| 2 | 0.00 | 0.00 | −2,700.00 | −7,400.00 | −19,400.00 |
| 3 | 0.00 | 0.00 | −2,700.00 | −10,100.00 | −28,100.00 |
| 4 | 0.00 | 0.00 | −2,700.00 | −12,800.00 | −36,800.00 |
| 5 | 0.00 | 0.00 | −2,700.00 | −15,500.00 | −45,500.00 |
| 6 | 0.00 | 0.00 | −2,700.00 | −18,200.00 | −54,200.00 |
| 7 | 0.60 | 87.89 | −2,612.11 | −20,812.11 | −62,812.11 |
| 8 | 1.18 | 172.26 | −2,527.74 | −23,339.85 | −71,339.85 |
| 9 | 1.73 | 253.26 | −2,446.74 | −25,786.59 | −79,786.59 |
| 10 | 2.26 | 331.02 | −2,368.98 | −28,155.58 | −88,155.58 |
| 11 | 2.77 | 405.66 | −2,294.34 | −30,449.91 | −96,449.91 |
| 12 | 3.26 | 477.32 | −2,222.68 | −32,672.59 | −104,672.59 |
| 13 | 3.73 | 546.12 | −2,153.88 | −34,826.47 | −112,826.47 |
| 14 | 4.18 | 612.16 | −2,087.84 | −36,914.31 | −120,914.31 |
| 15 | 4.61 | 675.56 | −2,024.44 | −38,938.74 | −128,938.74 |
| 16 | 5.03 | 736.43 | −1,963.57 | −40,902.31 | −136,902.31 |
| 17 | 5.43 | 794.86 | −1,905.14 | −42,807.45 | −144,807.45 |
| 18 | 5.81 | 850.95 | −1,849.05 | −44,656.50 | −152,656.50 |

At the 15-account ceiling gross profit is 15 × 146.48 = 2,197.20 per month against 2,700 of fixed and acquisition spend, a permanent loss of CAD 502.80 per month before founder compensation. There is no trough; cash falls without limit.

**Missing inputs that the evidence cannot supply:** the real tier mix, refund rate on pilots, conversion from pilot to subscription, churn, support hours per account, the composition of the CAD 900 fixed cost, the QuickBooks developer programme fee, and the number of developers.

### 7.6 What the buyer gets, as modelled

All figures are the research record's assumptions **[assumption]**; none was measured.

- Clerk time: 600 invoices × 6 minutes = 3,600 minutes = 60 hours; 60 × CAD 32 = CAD 1,920 per month. If 80% of lines match automatically: 1,920 × 0.80 = CAD 1,536 (the brief rounds to "about 1,540").
- Mismatches caught: 0.3% × CAD 800,000 monthly purchases = CAD 2,400.
- Total 1,536 + 2,400 = CAD 3,936 per month (the brief says "about 3,900").
- The research record's invalidation threshold is CAD 500 per month of mismatches per distributor. At Starter that is 500 ÷ 249 = 2.0 times the price.

All three tiers billed monthly cost less than the assumed CAD 10,000 annual sign-off limit: 249 × 12 = 2,988; 449 × 12 = 5,388; 799 × 12 = 9,588.

## 8. Funnel recomputed from distinct reachable prospects

The chat gave "300 → 15 → 6 demos → 1-2 customers" **[chat]**. The rates behind it are reply 5%, meeting 40%, close 20% **[assumption]**. The chat did not say whether 300 means emails or companies, or whether "customer" means a paid back-test or a subscription.

Definition used here **[assumption]**: a distinct reachable prospect is one distributor legal entity, counted once however many people or messages are involved, that appears on a prospect list, has a named finance contact with a verified address, and has not been contacted before.

| Stage | Rate | Reading A | Reading B |
|---|---|---|---|
| Distinct prospects contacted | — | 300 | 300 |
| Replies | 5% | 15 | 15 |
| Demos | 40% | 6 | 6 |
| Paid back-tests | 20% | 1.2 | 1.2 |
| Subscriptions | A: every back-test converts. B: 50% convert | 1.2 | 0.6 |

Reading A is the chat's own ("1-2 customers"). Reading B takes the research record's weekly plan at its word: 2 paid back-tests in week 2 and 1 conversion in week 3, which is 50% **[assumption]**. Reading B is the downside case.

Checks:

- **Lead cost per subscription.** 300 × 3.50 = CAD 1,050. Reading A: 1,050 ÷ 1.2 = CAD 875. Reading B: 1,050 ÷ 0.6 = CAD 1,750. The model's CAD 1,500 lies between them and excludes founder time.
- **Qualification.** The research record's week-1 gate is that at least 5 of 8 visited distributors have purchase orders and digital receiving (62.5%). If only 62.5% of demos are with qualified accounts and only those can buy, paid back-tests fall to 6 × 0.625 × 0.20 = 0.75 **[assumption]**.
- **Prospects needed for two expected back-tests.** 2 ÷ (0.05 × 0.40 × 0.20) = 2 ÷ 0.004 = 500 distinct prospects.
- **Prospects needed for 27 accounts, ignoring churn.** Reading A: 27 ÷ 0.004 = 6,750, lead cost 6,750 × 3.50 = CAD 23,625. Reading B: 13,500. This understates the need, because accounts churn while the base is built.
- **Prospects needed for 27 accounts, with churn, as in section 7.5.** The base ramp adds accounts from month 7 and reaches 27 in month 39: 33 monthly cohorts × 300 = **9,900** distinct prospects, lead cost 9,900 × 3.50 = CAD 34,650. Positive monthly cash with founder compensation comes in month 44: 38 cohorts × 300 = **11,400**. Under Reading B (0.2% per prospect) 300 prospects a month cap the account base at 0.6 ÷ 0.025 = 24, below 27; the cap reaches 27 only above 26.93 × 0.025 ÷ 0.002 = 337 prospects a month.
- **Universe size is a missing input.** No source was consulted for the number of Lower Mainland wholesale distributors that meet the ideal-account definition and use QuickBooks Online Plus or Advanced with purchase orders. If it is below 9,900, founder-paid break-even cannot come from cold outreach in this market alone at these rates (section 1). Task T-0.1.1 counts the list before outreach starts and compares it with 500 (enough for one cohort), 9,900 and 11,400.
- **The research record's weekly targets do not follow from its rates.** It targets 6 discovery calls in week 1 and 3 paying pilots by week 4. The rates give 6 demos and 1.2 back-tests from the whole month's 300 prospects.

## 9. Stop rule

**As stated in chat [chat]:** stop if there are fewer than 2 back-tests in 30 days, or if customers do not record receiving at all.

**Which rule is in force.** The chat's rule, with its 30-day window, is in force until the founder accepts a revision. The revision below is a proposal. Metrics M-1a and M-1b and Gate A in [execution-plan.md](execution-plan.md) carry both, each with its own target, and T-0.2.4 evaluates both.

**Consistency check of the chat's rule.**

| Test | Result |
|---|---|
| Expected conversions | 300 prospects give 1.2 expected paid back-tests, below the threshold of 2 |
| Sample size | With 6 demos at 20% each, the chance of 2 or more sales is 1 − 0.8⁶ − 6 × 0.2 × 0.8⁵ = 1 − 0.2621 − 0.3932 = **34%**. A funnel performing exactly as assumed would trigger "stop" about two times in three |
| Time to close | The sales cycle is 35 days [chat]. A 30-day window closes before the average prospect contacted on day 1 has decided, and long before one contacted in week 4 |
| Warm introductions | The first 10 offers go to warm introductions [assumption]. Their conversion rate is unknown and is not the cold-outreach rate, so a pass on warm leads says little about the channel |

**Proposed revision [assumption], for the founder to accept or reject:**

1. Contact a cohort of 500 distinct prospects in days 1–21, and record warm introductions separately. Lead cost 500 × 3.50 = CAD 1,750, which is CAD 550 above the research record's CAD 1,200 go-to-market budget; the founder must fund the difference or accept a cohort of 340 (1,200 ÷ 3.50 = 342), which the budget covers.
   **Scheduled volume.** [Section 12.4](#124-channel-sequence-and-weekly-volume) finds that 500 in 21 days is 167 a week, more than one founder can send, and schedules 300 (100 a week). On 300 the last row of the table below applies to clause 3: it passes 33.8% of the time with the funnel as assumed. The cost is then 300 × 3.50 = CAD 1,050, inside the budget. Section 12.8 sets out the choice this leaves.
2. Check at **day 60** (day 21 plus the 35-day cycle is day 56). Thirty-five days is an average, so about half of the last week's contacts will not have decided by then.
3. **Stop** if fewer than 2 back-tests are paid from cold outreach by day 60.
4. **Stop** if fewer than 5 of the first 8 qualified distributors can show independent receiving evidence (class A or B of section 3) for at least half of a sample of 20 purchase-order lines from last month. The 5-of-8 gate is the research record's; the sample and the one-half threshold are the author's.
5. **Stop** if back-tests on 3 distributors each find less than CAD 500 per month of qualifying discrepancies (the research record's invalidation test, using the definition of section 5.1).

**How often the revised rule gives the wrong answer.** The threshold of 2 equals the expected number of sales (500 × 0.05 × 0.40 × 0.20 = 2.0), so the rule is still weak. All figures are binomial calculations on the assumed rates **[assumption]**.

| Situation | Chance of passing clause 3 (2 or more sales) | Chance of a wrong outcome |
|---|---|---|
| Funnel exactly as assumed, 500 prospects, each converting at 0.4% | 1 − 0.996⁵⁰⁰ − 500 × 0.004 × 0.996⁴⁹⁹ = 59.5% | **False stop 40.5%** |
| Same, given exactly 10 demos were held | 1 − 0.8¹⁰ − 10 × 0.2 × 0.8⁹ = 62.4% | False stop 37.6% |
| Only 62.5% of demos are with qualified accounts (per-prospect rate 0.25%) | 35.5% | False stop 64.5% |
| Funnel at half the assumed rate (0.2%), which could not sustain the business | 26.4% | **False go 26.4%** |
| Cohort of 300 (the chat's number), funnel as assumed | 33.8% | False stop 66.2% |

Clause 4, the 5-of-8 gate, passes 65.1% of the time when the true share of distributors with independent receiving evidence is 62.5%, and 17.4% of the time when it is 40%.

**What this means.** With one or two expected sales, no threshold separates a working funnel from a failing one. The author's proposal is to accept a false-stop risk of about 40% on clause 3, because a wrong "stop" costs two months and about CAD 2,000–2,550 of out-of-pocket cash (the CAD 2,000 validation budget plus the CAD 550 cohort overrun; the ramp in section 7.5 charges a deliberately conservative CAD 7,400 for the same two months, or CAD 19,400 with founder compensation) while a wrong "go" costs the build (338–534 hours) and the ramp of section 7.5. The founder may instead: (a) set the threshold at 1 sale, which passes 86.5% of the time at the assumed rate but also 63.2% of the time at half the rate; or (b) treat a miss on clause 3 as "extend one more cohort" when replies and demos are at or above the assumed 25 and 10. Nothing in this repository can make the rule reliable; only more prospects or higher conversion can.

The chat's 30-day rule stays on record and in force until the founder decides.

## 10. What buyer evidence would change the decision

| Evidence | Change |
|---|---|
| 5 or more of 8 distributors hand over independent receiving records and 2 or more pay for a back-test | Proceed to build (Phase 1 onward) |
| Most distributors have receiving only through QuickBooks bills | Stop the three-way product. Reconsider as a duplicate and price-variance check at a lower price, a different product that this plan does not cover |
| Back-tests find qualifying discrepancies of CAD 500 or more per month | Supports Starter pricing; use the dollar figure as the outreach hook |
| Controllers will pay only if results are posted into QuickBooks | Bring forward the deferred bill-posting feature ([PRD.md](PRD.md) section 9) |
| Prospects are mostly on Sage 50 | Out of scope for this plan; a file-based pilot is possible but the desktop connector is a separate project |
| The reachable list has fewer than 500 distinct prospects | The cold-outreach test cannot be run as designed; rely on referral partners and re-plan |

## 11. Open decisions for the founder

1. Accept or reject the revised stop rule in section 9, including its stated false-stop risk and the CAD 550 budget overrun for a cohort of 500. The go-to-market plan schedules 300, not 500; on 300 clause 3 passes 33.8% of the time, so also choose between (a) and (b) in [section 12.8](#128-first-30-60-and-90-days) before day 1.
2. Accept, change or reject the refund criterion in section 5.1, including the CAD 500 threshold and the accepted residual risk.
3. Confirm the definitions of paying account and billable unit in section 6.
4. Supply the composition of the CAD 900 monthly fixed cost and the location of the VPS (affects data-residency statements in [TRD.md](TRD.md)).
5. Confirm who signs and pays for the pilot (section 2), what the CAD 500 covers and how Phase 0 back-tests are delivered by hand (section 5).
6. Choose the full build (338–534 hours) or the smaller cut (142–225 hours, about month 6) in [execution-plan.md section 5](execution-plan.md#5-estimate-summary), and say who builds. The full build has two readings ([section 7.5](#75-cash-required-during-the-acquisition-ramp)). (a) First subscription about month 7 with a developer other than the selling founder; that developer's cost, CAD 33,800–53,400 at CAD 100 an hour [assumption], is outside the ramp and deepens the trough to CAD −61,626 on the low estimate, or −83,926 on the high estimate with the first subscription in month 8 (without founder compensation). (b) A founder who builds alone and keeps selling: first subscription in month 8 (trough CAD −30,526 without founder compensation, −197,541 with) or month 11 (−38,626 and −223,641).
7. Accept or change the definition of independent receiving evidence in section 3.
8. Accept or change the go-to-market plan in [section 12](#12-go-to-market-plan): the weekly volume of 100 emailable prospects (12.4), the order-form step from pilot to subscription (12.6) and the three channel signals (12.9). Before T-0.2.2 sends anything, either obtain a lawyer's confirmation of the anti-spam reading in 12.4, or record here in words that the founder accepts the risk of sending on the author's unverified reading, with a maximum penalty of CAD 1,000,000 for an individual [source: SRC-13].

## 12. Go-to-market plan

How the first paying accounts are to be won. Nothing here has been done and no message has been sent to anyone. Every number in this section is **[assumption]** unless it is marked **[chat]** or **[source: SRC-nn]**; rates and counts taken from other sections keep the label they have there. Where another section already holds the content, this section cites it.

### 12.1 Ideal customer profile

| Item | Record |
|---|---|
| Firm, size, region | As in [section 2](#2-market-people-and-current-practice): Lower Mainland food, building-supply and industrial wholesale distributors on QuickBooks Online Plus or Advanced with purchase orders enabled; revenue CAD 5–50 million, 20–150 employees, 1–4 accounts-payable staff, 200–1,500 supplier invoices a month [assumption] |
| Trigger that makes them need it now | The buying triggers of section 2: a duplicate or overpayment just discovered, the clerk leaving, a year-end audit finding, volume beyond one clerk [assumption]. Discovery asks "when did you last find an overpayment or duplicate?" and the funnel log records the answer |
| Qualified | The qualification rule of section 2, unchanged |
| Disqualified, do not offer the pilot | (1) Books on Sage 50, QuickBooks Desktop or Enterprise, or a QuickBooks Online plan below Plus (no purchase orders [source: SRC-06]). (2) Purchase orders for under 70% of purchases, or under 200 supplier invoices a month. (3) Already running a procurement suite or an accounts-payable tool with three-way match. (4) Most supplier invoices in a currency other than CAD; the planned rules do not convert (test UT-29) (author proposal). (5) Outside the Lower Mainland, for the launch cohort only |
| Recorded, not sold to | A firm that passes the rule but has no independent receiving evidence (class A or B, [section 3](#3-competitor-gap-what-was-read-today-and-what-was-not)). It is counted under stop-rule clause 4 of [section 9](#9-stop-rule). If its controller still wants the back-test, the agreement says in advance that the result will be two-way only |

### 12.2 Named roles

| Question | Role | Basis |
|---|---|---|
| Who feels the pain | The accounts-payable clerk, daily; the controller when an overpayment surfaces | Section 2 [assumption] |
| Who signs and pays | The controller; the owner where the controller cannot sign | Section 2 (author proposal, open decision 5) |
| Who can block | The owner (budget, under about CAD 10,000 a year); the warehouse or receiving lead, by not handing over the receiving log; whoever holds QuickBooks administrator rights, often an outside bookkeeper, by not granting read access | Owner from section 2; the other two are author assumptions to be confirmed in T-0.1.2 |
| Who supplies the sample data | Controller: QuickBooks read access and the evidence-class attestation. Clerk: invoice and credit-note PDFs and earlier invoices on open purchase orders. Receiving lead: the warehouse record | Inputs listed in [section 5](#5-offer-channel-and-pilot) |

### 12.3 Prospect list

- **Sources.** Those named in section 5. None of the lists was opened; their size and terms of use are unverified, no source consulted ([section 13](#13-sources-and-assumptions)).
- **How many exist.** Unknown: a missing input (section 8, "Universe size"). T-0.1.1 produces two counts: all distinct entities, and the **emailable** ones defined below. Both are compared with 300 (one month of this plan), 9,900 and 11,400.
- **How it is built.** T-0.1.1 in [execution-plan.md](execution-plan.md): pull the lists, merge on legal name and address, drop entities outside 12.1, add one named finance contact per entity. Cost CAD 3.50 per row (section 5).
- **Consent basis per row.** For each contact the list records where that person's or firm's email address is published (the page address and the date seen), whether the page carries a statement refusing unsolicited messages, and so one of two values: *emailable* (published by the firm or the person, no such statement, and the contact's role covers supplier invoices) or *phone only*. An address guessed from a pattern, returned by a contact-finding tool or read from LinkedIn is phone only, whether or not a verification tool says it delivers. The reason is in 12.4.
- **How it is checked.** One row per legal entity; source recorded per row; a named contact on at least 80% of rows; and a hand check of 20 random rows against the firm's own website for "still trading", "wholesale", "Lower Mainland" and, on emailable rows, that the address is where the row says it is (author proposal). If more than 4 of the 20 fail, the list is rebuilt before any send. Whether a firm uses QuickBooks Online cannot be read from a list; it is learned at the reply or the call, which is why the funnel counts qualification separately.

### 12.4 Channel, sequence and weekly volume

First channel to test: direct outreach to controllers, leading with the paid back-test (section 5). The first 10 offers go to warm introductions and are logged apart from cold outreach (section 5; metrics M-1a and M-1b).

**What Canada's anti-spam law allows, as the author read it.** This is the author's reading of the statute, not legal advice, and no lawyer has seen it. The Act [source: SRC-13] and its Regulations [source: SRC-14] were read on 2026-11-10 through a summarising page fetch, so wording below is paraphrase. The regulator's guidance and the regulations that prescribe the form of the identification were not read: unverified, no source consulted.

| Point | What the text says | Effect on this plan |
|---|---|---|
| What is covered | Section 6 prohibits sending a commercial electronic message to an electronic address without the recipient's express or implied consent. "Electronic address" covers email, instant-messaging, telephone and similar accounts, and a message is commercial by its purpose. The Regulations give no general exemption for business-to-business messages between strangers | A LinkedIn connection note or message sent to open a sale is covered as well as an email, however it is worded. The earlier idea of LinkedIn as a fallback is dropped |
| Implied consent this plan can rely on | Section 10(9)(b): the recipient has conspicuously published the address, or caused it to be published; the publication carries no statement that they do not want unsolicited commercial messages; and the message is relevant to their business role or duties | Email goes only to *emailable* rows (12.3). The first touch is about checking supplier invoices and goes to the person responsible for them |
| No consent basis | An address found or inferred by a tool was not published by the recipient. Section 13 puts the burden of proving consent on the sender | *Phone only* rows are never emailed. The list keeps the proof for every emailable row |
| Telephone | Section 6(8)(a): section 6 does not apply to an interactive two-way voice conversation | The phone call is the only step open for phone-only rows. Canada's telemarketing rules were not read: unverified, no source consulted |
| After a call or a reply | Section 10(9)(c): consent is implied where the recipient gave the sender the address without saying they do not want such messages, and the message is relevant to their role | If a contact on a call asks for details by email, that email may be sent to the address they give; the log records the date and their words |
| Warm introductions | Regulations section 4: the consent rule does not apply to the first message sent after a referral by someone who has a business or personal relationship with both sender and recipient, provided the message gives the referrer's full name and says it is sent because of the referral | Every warm-introduction email names the referrer in full and says so. Only that first message is covered; a second needs a reply or another basis |
| Content of every message | Section 6(2): identify the sender, give contact information that stays valid for 60 days (section 6(3)), and include an unsubscribe mechanism. Section 11(3): an unsubscribe request is honoured within 10 business days | All three emails of 12.5 carry the same footer. The funnel log has a "do not contact" date per prospect, checked before every send |
| Penalty | Section 20(4): the maximum penalty for a violation is CAD 1,000,000 for an individual | The first send waits for a lawyer's confirmation of this table, or for the founder's written acceptance of the risk under open decision 8. An experienced peer's opinion is not enough for this point |

**Sequence for one prospect.**

| Day | Emailable row | Phone-only row |
|---|---|---|
| 0 | First-touch email (12.5) | No message. May be chosen for a call |
| 4 | Phone call to the main line asking for accounts payable, for the 30 best-fitting prospects of the month, emailable or not | The same |
| 7 | Follow-up email (12.5) | — |
| 14 | Closing email: two lines saying this is the last note and repeating the offer in one sentence, with the same footer. No further contact unless they reply | — |
| On a reply or a call that leads somewhere | A 20–30 minute discovery call (T-0.2.5): the five discovery questions of T-0.1.2, the qualification rule, "who signs a CAD 500 pilot", then a walk through a synthetic sample report. No application exists in Phase 0, so this call is the "demo" of section 8 | The same |

LinkedIn is used to find who holds the finance role, not to send messages.

**One volume, used everywhere in this plan.** 100 new emailable prospects a week for three weeks, and no new sends in the fourth week, which goes to calls, follow-ups and hand delivery of back-tests. That is 100 × 3 = **300 a month**, the chat's 300 **[chat]**, or 300 ÷ 4.33 = 69 a week on average. Founder time: 12–18 hours a month on sending and the 30 calls (T-0.2.2) and 8–12 on discovery calls (T-0.2.5), so 20–30 hours a month, 5–7.5 a week; this assumes templated sends through an email tool with only the name and firm changed by hand. The schedule (12.8), the tasks and their hours, and the stop-rule probabilities quoted in 12.8 all use this volume. The 500-prospect cohort in clause 1 of section 9 would need 167 a week (500 ÷ 3), which one founder cannot sustain beside the census and the hand match; this plan does not schedule it, and section 9 now says what clause 3 is worth on 300.

**Reconciliation with the funnel, the ramp and the acquisition cost.**

| Step | Arithmetic | Result per month |
|---|---|---|
| New emailable distinct prospects | 100 × 3 waves | 300 |
| Replies at 5% | 300 × 0.05 | 15 |
| Discovery calls at 40% | 15 × 0.40 | 6 |
| Paid back-tests at 20% | 6 × 0.20 | 1.2 |
| Paying accounts, Reading A (every back-test converts) | 1.2 × 1.00 | **1.2** |
| Paying accounts, Reading B (half convert) | 1.2 × 0.50 | 0.6 |

1.2 is the "New" column of the base ramp in [section 7.5](#75-cash-required-during-the-acquisition-ramp) and 0.6 that of the downside case; the rates are those of [section 8](#8-funnel-recomputed-from-distinct-reachable-prospects). The ramp spends CAD 1,800 a month, which is 1.2 × the model's CAD 1,500 by definition and so confirms nothing; the only identified cash is list cost, 300 × 3.50 = 1,050 a month, CAD 875 per account on Reading A (section 8). Timing: 35 days **[chat]** from first contact to a paid back-test; a recurring account can start only once the application exists, month 7 in the base case. Back-tests sold before then wait for release (section 5); at 1.2 a month the ramp could have about five waiting when the application is released, and it does not count them, which is conservative.

**The funnel restated on emailable rows.** The 5% reply rate is an email rate. The brief gives no conversion rate for phone-only prospects, so they add nothing to the expected numbers. The share of list rows that are emailable is unknown until T-0.1.1.

| Emailable share of the list | List rows needed for 300 emailable a month | List cost a month (× 3.50) | List cost per paying account (÷ 1.2) | Expected paid back-tests if only 300 rows are built |
|---|---|---|---|---|
| 100% | 300 | 1,050 | 875 | 300 × 0.004 = 1.2 |
| 50% | 600 | 2,100 | 1,750 | 150 × 0.004 = 0.6 |
| 25% | 1,200 | 4,200 | 3,500 | 75 × 0.004 = 0.3 |

Below a share of 1,050 ÷ 1,800 = 58%, list cost alone exceeds the CAD 1,800 a month the ramp allows for all acquisition. The thresholds of section 8 (9,900 and 11,400) are counts of prospects who can be contacted, so here they mean emailable rows; at a 50% share the list would need 19,800 rows for 27 accounts. The limit of the launch market stated in [section 1](#1-proposed-decision) is therefore tighter than section 8 shows, by a factor nobody knows yet.

### 12.5 Messages (synthetic; never sent)

The firm and the people are invented. Neither message quotes a result, because none exists; once T-0.1.4 has produced one, the founder may add one sentence stating that single figure and that it comes from one distributor. Every email, including the day-14 closing note, ends with the same footer.

**First touch**

> Subject: Checking supplier invoices against what was received at Fictional Distributor A
>
> Hello Ms. Example,
>
> I am a Vancouver developer working on one narrow thing for wholesale distributors on QuickBooks Online: checking every supplier invoice line against the purchase order and against your own receiving record, then listing only the lines that do not agree.
>
> The offer is a back-test of last month for CAD 500. If the discrepancies we can evidence come to less than CAD 500, the fee is refunded.
>
> From you it needs four things: read-only access to purchase orders and bills in QuickBooks; last month's supplier invoice and credit-note PDFs; for any purchase order still open from earlier months, the earlier invoices and credit notes on it; and your warehouse receiving log or receiver-signed delivery slips for those orders. Without a receiving record of your own the check is two-way only, and I would tell you that before you pay.
>
> Would 20 minutes next week be useful? If someone else looks after accounts payable, I would be glad to be pointed to them.
>
> [Founder's full name], [business name]
> [Postal address] · [phone] · [email]
> I wrote to this address because it is published on [page] as the contact for accounts at Fictional Distributor A. To receive nothing further from me, reply "stop" or use [unsubscribe link]; I will remove you within 10 business days.

**Follow-up, day 7**

> Subject: Re: Checking supplier invoices against what was received at Fictional Distributor A
>
> Hello Ms. Example,
>
> One addition to my note of last week. The back-test is done by hand for now. Your side is to connect QuickBooks, send the invoice PDFs with the earlier invoices on still-open purchase orders, export the receiving log, and confirm in one line who keeps that log. You get the report within 15 business days. It lists short shipments, price differences against the purchase order and duplicate invoices, each with its documents, and it also says how many lines could not be checked.
>
> The CAD 500 covers that report and, once the application is released, 30 days of the same check on new invoices before they are paid. Nothing recurs unless you choose a monthly plan afterwards.
>
> If this is not a problem at Fictional Distributor A, a one-line reply saying so helps me too.
>
> [Founder's full name], [business name]
> [Postal address] · [phone] · [email]
> To receive nothing further from me, reply "stop" or use [unsubscribe link]; I will remove you within 10 business days.

The refund wording follows the proposal of [section 5.1](#51-refund-criterion-proposal) and changes if the founder changes it. Neither message says how much of the clerk's time the inputs take; that is unknown until T-0.1.4 has measured it. "Read-only" is used only if T-1.1.1 or Intuit's consent screen confirms such a scope exists; otherwise the sentence says "we read and never write". A warm-introduction email opens instead with the referrer's full name and the statement that it is sent because of that referral (12.4).

### 12.6 Pilot offer and the step to a recurring account

| Item | Record |
|---|---|
| What the buyer gets, pays and supplies | Section 5: the 30-day pilot for CAD 500 **[chat]**, the four inputs listed there, hand delivery within 15 business days while no application exists |
| What ends the pilot | Day 30 of live checking. The refund is decided once, on the governing report (section 5.1). For a Phase 0 account the 30 days run from the day the application is released to it |
| Exact step to a recurring paid account (author proposal) | At the report review session (T-7.2.2), and no later than day 25, the founder gives the controller a one-page order form. It names the tier by the invoice and credit-note count measured during the pilot (up to 300 Starter, up to 800 Pro, up to 2,000 Business; prices **[chat]**), monthly billing, and a start date of day 31. The controller, or the owner where the controller cannot sign, signs it and pays the first month through a manually issued invoice or payment link (PRD section 9 defers in-app billing). The account counts as paying when that first payment is received |
| If the form is not signed by day 30 | Live checking stops on day 30. Nothing is charged. The report stays with the buyer; data is deleted on the schedule of the pilot agreement |

The pilot-to-subscription rate is unknown (missing inputs, section 7.5). Reading A takes it as 100% and Reading B as 50%.

### 12.7 Three likely objections

| Objection | Honest answer |
|---|---|
| "Our clerk already checks invoices against the purchase order and packing slip." (the current workaround) | That may be enough, and the back-test is how to find out. The research record says many firms check only totals or invoices above a threshold [assumption]; nobody has measured it here. If the back-test evidences under CAD 500 of discrepancies in a month, the fee is refunded and the honest conclusion is that the manual check works |
| "We do not record receiving in QuickBooks." | Nobody does in the sense that matters: the quantity QuickBooks shows as received appears to come from entering the bill ([section 3](#3-competitor-gap-what-was-read-today-and-what-was-not), still an assumption). What is needed is a warehouse log or delivery slips signed by the receiver. A supplier's unsigned packing slip does not count. With neither, the report is a two-way check, every line reads "receipt absent", and the pilot is probably not worth CAD 500 to that firm |
| "We already pay for BILL" or "BILL does this." | BILL's pricing page lists two-way matching from its Corporate plan at $89 per user per month and three-way matching only on the custom-priced Enterprise plan [source: SRC-01]. If a two-way check is enough, BILL Corporate for two users costs about the same as MatchDesk's Starter tier (section 4) and already handles payments; MatchDesk is not the better buy there. MatchDesk is for the firm that wants the receipt checked as well and wants to keep purchasing in QuickBooks. Nothing is claimed about BILL in Canada (section 3) |

Two objections from the research record are answered elsewhere: supplier item codes that differ from the firm's own (the alias map, PRD MH-10) and Sage 50 (disqualified, 12.1). The research record's answer that scanned packing slips can serve as the receipt is **not** used: it holds only for receiver-signed slips (class B).

### 12.8 First 30, 60 and 90 days

Day 1 is the first send, after T-0.1.1 and the confirmation of 12.4. Each month repeats 12.4: waves of 100 emailable prospects on days 1–7, 8–14 and 15–21 of the month. A wave is counted as decided 35 days after it ends, so the first month's waves are decided on days 42, 49 and 56 and the second month's on days 72, 79 and 86. Thirty-five days is an average; real sales will spread around these dates.

| Cumulative by | Day 30 | Day 60 | Day 90 |
|---|---|---|---|
| Emailable prospects contacted (100 a week in three weeks of four) | 300 | 600 | 900 |
| Expected replies (5%) | 15 | 30 | 45 |
| Expected discovery calls (40%) | 6 | 12 | 18 |
| Waves decided | 0 of 3 | 3 of 6 | 6 of 9 |
| Expected paid back-tests from cold outreach (0.4% of decided prospects) | 0 | 300 × 0.004 = 1.2 | 600 × 0.004 = 2.4 |
| Stop rule read at this point | The chat's rule, in force: 2 paid in 30 days | Clause 3 of the proposed revision: 2 paid from cold outreach | Clause 3 again, only if the founder extended at day 60 (read on day 86) |
| Chance that rule passes if the funnel performs exactly as assumed | From cold outreach alone, close to nil: no wave is decided. It can pass only on warm introductions, whose rate is unknown | **33.8%** (300 decided) | 69.2% (600 decided) |
| Chance it passes if the funnel runs at half the assumed rate | — | 12.2% | 33.7% |
| Recurring paid accounts | 0 | 0 | 0 |
| List cost at a 100% emailable share (CAD 3.50 each; see 12.4 for lower shares) | 1,050 | 2,100 | 3,150 |
| Cash out as the ramp of section 7.5 charges it, without founder | 4,700 | 7,400 | 10,100 |
| The same, with founder compensation | 10,700 | 19,400 | 28,100 |
| Pilot fees received before refunds, net of card fee (not in the ramp) | 0 | 1.2 × 485.20 = 582.24 | 2.4 × 485.20 = 1,164.48 |
| Founder hours, from the task estimates | 69–109 | 107–170 | 142–224 |

- **What this schedule means for the stop rule, stated plainly.** Run exactly as scheduled, with the funnel performing exactly as assumed, this plan fails the chat's 30-day rule unless warm introductions supply the sales, and fails clause 3 of the proposed revision at day 60 about two times in three (66.2%, the "cohort of 300" row of section 9). A "stop" at Gate A is therefore the likely result even of a working funnel. What follows is a choice the founder makes before day 1, under open decision 1: (a) accept that and stop at day 60 on a miss; or (b) decide now that a miss at day 60 with at least 15 replies and 6 discovery calls from the first 300 means one more cohort, read on day 86, where 600 decided prospects give a 69.2% chance of passing and a failing funnel at half the rate still passes 33.7% of the time. Option (b) is option (b) of section 9 made specific; it moves Gate A by about one month, which adds CAD 2,700 to the cash trough without founder compensation and CAD 8,700 with it (section 7.5).
- **The day-90 column exists only if outreach continues past day 60:** after a pass at Gate A, or under choice (b). After a stop at day 60 there is no third month.
- **Recurring accounts stay at zero through day 90** because no application exists; the first is expected in month 7 or 8 (section 7.5). What these 90 days can produce is paid back-tests and the evidence for Gate A.
- **Money.** The research record's go-to-market budget is CAD 1,200 inside CAD 2,000 cash for the first 30 days (section 5); the month-1 list cost of 1,050 fits inside it only if nearly every row is emailable (12.4). The ramp's higher figures are the ones the economics use.
- **Founder hours.** Day 30: T-0.1.1 to T-0.1.5 (45–71) + T-0.2.1 (4–8) + one month of T-0.2.2 and T-0.2.5 (20–30) = 69–109; the research record says 80. Day 60 adds a second month of outreach and calls (20–30), T-0.2.3 (2–4), T-0.2.4 (2–3) and hand delivery (T-0.2.6) of 1.2 back-tests at 12–20 hours each (14.4–24.0): 107.4–170. Day 90 adds a third month (20–30) and 1.2 more deliveries (14.4–24.0): 141.8–224. The Phase 0 total in execution-plan.md section 5 (97–156 hours) covers one month of outreach, the first hand match and two deliveries; further months of outreach and further deliveries are extra. From month 3 the same selling and delivery take 34–54 hours a month from whoever does them, which is why section 7.5 gives a later first subscription for a founder who also builds.
- **Weekly targets, weeks 1–3 of each month:** 100 first-touch emails, 10 phone calls, last week's follow-ups, 5 expected replies and 2 discovery calls. **Week 4:** no new sends; closing notes, remaining calls, hand delivery. In month 1 the eight census visits of T-0.1.2 and the hand match of T-0.1.4 run alongside.

### 12.9 GTM stop rule

**The product** is dropped on the rule of [section 9](#9-stop-rule): the chat's rule is in force, the revision is a proposal, and clauses 4 and 5 (receiving evidence, discrepancies under CAD 500) are what say the product, not the channel, has failed. Nothing here replaces it.

**The channel** needs earlier signals, because replies and calls arrive weeks before sales. The three below are author proposals, checked for each month's 300 prospects 14 days after its third wave (day 35 for the first month). Percentages are binomial calculations on the assumed rates.

| Signal | Chance of seeing it if the funnel is as assumed | If the rate is half | What it means |
|---|---|---|---|
| Fewer than 8 replies from 300 (expected 15) | 1.6% | 52.4% | First time: change the list source or the message once. Two months running: drop cold email as the first channel and move to the backup channel of section 5 |
| Fewer than 3 discovery calls from 15 replies (expected 6) | 2.7% | 39.8% | Replies are not turning into conversations: the offer as worded is the problem, not the list. Rewrite 12.5 once before the next wave |
| No paid back-test from 12 discovery calls (two months, read on day 86) | 6.9% | 28.2% | The price or the refund terms are failing. Stop spending on outreach and re-plan the offer. This signal is reached only under choice (b) of 12.8: clause 3 was missed at day 60 and the founder extended by one cohort. If the founder did not extend, clause 3 has already stopped the plan at day 60 |

Replies and calls at or above expectation with sales below it at day 60 is the case choice (b) of 12.8 covers. The fit of pilot to subscription cannot be read inside 90 days; it is judged at Gate B (T-7.2.4).

## 13. Sources and assumptions

Date consulted for every row: **2026-11-10**. Access was through an automated page fetch; pages that render with scripts could not be read.

| ID | Source | Jurisdiction / scope | What it was used for | Access restriction |
|---|---|---|---|---|
| SRC-01 | BILL pricing page, `bill.com/pricing` | Vendor's US page; AP plan list prices and feature tiers; currency not named on plans | Plan prices; tiers that include two-way and three-way matching | None |
| SRC-02 | Precoro pricing page, `precoro.com/pricing` | Global vendor page; list prices billed annually | Core, Automation and AP Module prices; matching and QuickBooks Online on Core | None |
| SRC-03 | ProcurementExpress pricing page, `procurementexpress.com/pricing/` | Global vendor page; currency code not shown | Plan prices; absence of the term "three-way matching"; "Scan & Match" on Best only | None. The brief's own reference (a GetApp listing) was not opened |
| SRC-04 | Stampli pricing page, `stampli.com/pricing/` | Vendor's US page | No public price; matching statement; listed accounting systems | None |
| SRC-05 | Procurify pricing page, `procurify.com/pricing/` | Vendor page | No public price; three-way matching not named | None. The brief's review-site reference was not opened |
| SRC-06 | QuickBooks Online Canada pricing, `quickbooks.intuit.com/ca/pricing/` | Canada; list prices in CAD; promotional prices also shown | Plus and Advanced include purchase orders and inventory; regular prices | None |
| SRC-07 | Two threads on Intuit's community site: "How to receive partial shipment" (answer dated 2020-04-23) and "Can I do backorder tracking on QuickBooks Online Plus" (answer dated 2020-03-19, en-ca) | Intuit-hosted user forum; QuickBooks Online | No item receipt; partial quantities through linked bills, expenses or cheques; "Received" column; automatic closing | Forum answers, six years old, one author not identified as staff. Not official documentation |
| SRC-08 | Stripe Canada pricing, `stripe.com/en-ca/pricing` | Canada; standard published rates | 2.9% + CAD 0.30 for domestic cards; pre-authorised debit 1% + CAD 0.40 capped at CAD 5.00 | None |
| SRC-11 | Intuit Australia product post "Easily keep track of backordered items", `quickbooks.intuit.com/au/blog/product-update/easily-keep-track-backordered-items/` | Australia; QuickBooks Online Plus; page metadata dates 2017-07-19 and 2023-07-05 | Several bills, expenses, cheques per purchase order; "Received" column; "Closed" tick; no item receipt mentioned | Vendor marketing post, not documentation. Pointed out by the independent reviewer (F-022) and then opened by the author |
| SRC-12 | Intuit community thread "Process for receiving partial items on a PO…", reply by a QuickBooks Team member dated 2023-08-02 | Intuit-hosted forum, en-us; QuickBooks Online | Purchase orders close automatically when all quantities are added to bills, expenses or checks | Staff forum reply, not documentation. Does not state whether an item receipt exists. Pointed out by the reviewer (F-022) and then opened by the author |
| SRC-13 | Justice Laws, *An Act to promote the efficiency and adaptability of the Canadian economy by regulating certain activities that discourage reliance on electronic means of carrying out commercial activities…* (S.C. 2010, c. 23), `laws-lois.justice.gc.ca/eng/acts/E-1.6/`; page states current to 2026-10-19, last amended 2026-01-01 | Canada, federal statute | Sections 1(1), 1(2), 6(1) to 6(3), 6(8), 10(9), 11(3), 13, 20(4), as used in section 12.4 | Read through a summarising page fetch that returns short quotations and paraphrase; the author did not see every provision word for word. The author's reading, not legal advice |
| SRC-14 | Justice Laws, Electronic Commerce Protection Regulations, SOR/2013-221, `laws-lois.justice.gc.ca/eng/regulations/SOR-2013-221/`; page states current to 2026-10-19 | Canada, federal regulations | Section 3 (excluded messages; no general business-to-business exclusion between strangers; messaging services only with consent) and section 4 (first message after a referral) | Same restriction as SRC-13 |
| SRC-09 | GitHub Spec Kit README and `spec-driven.md` | Method reference | Requirement, plan and task structure; see below | None |
| SRC-10 | arc42 overview, `arc42.org/overview/` | Method reference | Section checklist for [TRD.md](TRD.md) | None |
| — | Intuit developer documentation (PurchaseOrder entity, API features, partner programme FAQ) | — | Not read | Pages returned only a title. Every statement about the QuickBooks API in this repository is **unverified, no source consulted** until T-1.1.1 |
| — | Intuit help article on adding a purchase order to a bill | — | Not read | HTTP 404 on two URL variants |
| — | Prospect lists and associations named in section 5 | — | Not read | Not attempted; their size and terms of use are **unverified, no source consulted** |
| — | Regulator's guidance on the anti-spam law, the regulations prescribing the form of sender identification, and Canada's telemarketing rules | — | Not read | Not attempted by the author; the reviewer reported HTTP 403 on the regulator's guidance page. **unverified, no source consulted** |
| — | Extraction model pricing | — | Not read | The CAD 0.03 per invoice figure is a model assumption |
| — | WCAG 2.2 and OWASP ASVS 5.0.0 | — | Criteria in [design.md](design.md) were cited from the author's knowledge. ASVS requirement numbers in [TRD.md](TRD.md) are those the independent reviewer cited from ASVS 5.0.0 in review round 1; the author did not open either standard | The reviewer reported that all WCAG criterion numbers, names and levels in design.md are correct |

**How the two method resources were used.**

- Spec Kit [SRC-09]: informed three checks. Must-haves in [PRD.md](PRD.md) state what and why with acceptance criteria and no technology; stack choices appear only in [TRD.md](TRD.md) with a reason tied to a requirement; tasks in [execution-plan.md](execution-plan.md) each carry an acceptance check, and tasks that can run in parallel are marked. Unsettled points are marked "not decided in chat" in the way Spec Kit marks needed clarifications.
- arc42 [SRC-10]: [TRD.md](TRD.md) follows its section list (goals, constraints, context, strategy, building blocks, runtime, deployment, cross-cutting concepts, decisions, quality requirements, risks, glossary); a mapping table is in TRD section 0.

**Items from the research record deliberately not used in calculations, with reasons.** Launch, minimum and maximum prices (CAD 299, 149, 999): not reconciled with the tiers in chat. USD and AED price lists and the US and UAE market scores: outside the launch market. Week-4 gate of CAD 750 MRR: cannot be met inside the sales cycle (section 5). "Pull item receipts from QuickBooks Online" and "post matched bills to QuickBooks": replaced and deferred, see section 3 and [PRD.md section 9](PRD.md#9-non-goals-and-deferred-items). Sage 50 file-based pilot and desktop connector: out of scope. Scale steps (QuickBooks app store listing, US verticals): after the pilot question is answered.

**Assumptions preserved unresolved.** Every unit-economics input; the tier mix; all funnel rates; the 35-day cycle applying to the back-test sale; the ideal-account description; the customer-benefit model; the brief's claim about BILL in Canada; the Procurify price; everything about the QuickBooks API; whether QuickBooks bills carry line quantities linked to purchase-order lines (needed for open-PO history); the definition of independent receiving evidence; the refund criterion; the author's reading of anti-spam law in section 12.4 and the share of prospects whose address is published.
