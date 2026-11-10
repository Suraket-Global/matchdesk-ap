# Design brief — MatchDesk AP three-way match

Number labels follow [Decision.md section 0](Decision.md#0-how-numbers-are-labelled). Sizes, spacings, durations and breakpoints are author proposals, so **[assumption]**. Contrast ratios were calculated by the author with the WCAG relative-luminance formula from the proposed hex values; they are arithmetic on assumptions, so **[assumption]**, and must be re-measured on the built screens. WCAG 2.2 success criteria are cited from the author's knowledge; the independent reviewer checked the criterion numbers, names and levels against the W3C quick reference in review round 1.

Screens are identified as in [App-flow.md](App-flow.md) (S-01 to S-19). Design decisions carry IDs DD-nn so other documents can cite them.

## 1. Who is looking and what they must see first

- **The accounts-payable clerk** sits at a desk, usually with two monitors, and works through tens of exceptions in a sitting. They need speed, the document beside the data, and the keyboard.
- **The controller** visits a few times a week, approves, and reads one report. They need totals they can defend and a clear line between what is proved and what is unknown.

Hierarchy that follows:

| Priority | What | Where it appears |
|---|---|---|
| 1 | What needs a person, and how much money it concerns | S-08 counters and value column; S-12 lists |
| 2 | The evidence for one decision | S-09 three panes |
| 3 | What could not be checked | Receipt coverage strip on S-08; Section 3 of S-13 |
| 4 | What has been approved versus what is still a draft | Status banner on S-13; status chips everywhere |
| 5 | Everything else | Settings, audit |

## 2. Design decisions

| ID | Decision | Why |
|---|---|---|
| DD-01 | The match view (S-09) is three fixed panes: invoice, purchase order, receipts and history, with the calculation written as a sentence underneath | A clerk trusts a result they can re-add by eye; this replaces three windows side by side |
| DD-02 | "Receipt absent" has its own colour, icon and word, and is never shown in the green family. Coverage and unverified dollars are stated wherever findings are stated | The pilot question turns on receiving data; an absent receipt must not read as fine |
| DD-03 | Status is always a word plus an icon plus a colour, never colour alone | Colour-blind users; printed reports |
| DD-04 | Draft and approved are different at a glance: DRAFT uses a violet banner and a diagonal watermark in exports; APPROVED uses a solid dark banner with name and date | A draft figure quoted to a supplier is a real risk |
| DD-05 | Machine-read values and human-entered values are marked differently (small "read" and "edited" tags); suggestions are shown as suggestions with a confirm button, never pre-applied | The user must know what a person has checked |
| DD-06 | QuickBooks "billed against PO" quantity and supplier-only packing slips are shown in the receipts pane, greyed, labelled "Not counted as a receipt" | Shows the user why MatchDesk's received quantity can differ from QuickBooks' "Received" column. The label states MatchDesk's rule (AD-05), not a claim about how QuickBooks works, which is unconfirmed until T-1.1.1 |
| DD-13 | Receipt absent always shows which of three cases it is: not received (log covers the order, shows nothing), supplier slip only, no receiving evidence | The first is a finding candidate; the others are unverified; the user must not confuse them |
| DD-14 | Work screens stack to one column instead of switching to read-only when the window is narrow or zoomed | A clerk using 200% zoom keeps every function |
| DD-07 | Money and quantities are right-aligned in tabular numerals with fixed decimals; variance values show sign and currency | Columns must add up visually |
| DD-08 | Long operations show counts that add up (queued + processing + ready + needs review + failed + duplicate = files) | Makes a skipped or lost file visible |
| DD-09 | Dialogs before approvals restate the decision in a sentence with its value | Prevents approving the wrong row |
| DD-10 | Full keyboard operation of the queue and match view, with visible shortcuts | Clerk throughput; accessibility |
| DD-11 | Desktop-first. Every function works down to 640 px of width; below that only reading and approving are supported | Matching work is not done on a phone, but 640 px is what a 1280 px screen gives at 200% zoom |
| DD-12 | Unit conversions are entered with a live worked example using the user's own numbers | The costliest mistake is a wrong conversion |

## 3. Layout

- **Shell.** Top bar 56 px: account name, navigation, QuickBooks status dot with word, user menu. Content area max width 1680 px; tables use the full width.
- **Grid.** 8 px spacing unit. Page padding 24 px. Table row height 40 px (32 px in a "compact" setting for the queue).
- **S-08 Exception queue.** Counters row (one per type, each a button that filters), coverage strip, filter bar, table. Selected row has a 3 px left bar and background tint.
- **S-09 Match view.** At 1440 px and wider: invoice pane 46%, purchase-order pane 24%, receipts pane 30%; calculation bar across the bottom of the two right panes; resolution bar fixed at the bottom. Between 1024 and 1439 px: invoice pane on the left at 50%, the other two stacked on the right. Pane dividers are draggable and keyboard-adjustable.
- **S-07 Extraction review.** Two panes 50/50: document left, fields right; failed checks pinned above the fields.
- **S-13 Report.** Single column 880 px for reading and printing; numbers in summary cards of equal size; tables below.

To sketch S-09: draw a page with a slim header. Left half: a PDF page with one row outlined in blue. Right top: a card titled "PO 4471 · line 2" with four values (Ordered 100 EA, PO price 4.20, Alias "TS-2x4-8 → 2X4-8-SPF, 1:1", Vendor). Right middle: a short table of receipts (3 Oct, 60, "receiving-oct.xlsx row 218"), a grey row "Billed against PO in QuickBooks: 100 · Not counted as a receipt", then earlier invoices. Right bottom: an amber box with the sentence "Received to date 60. Invoiced to date 100. Excess 40 × 4.20 = CAD 168.00." Along the bottom: a "Resolve as" control, a note field, and "Resolve and next". All names and numbers are synthetic.

## 4. Typography

| Use | Face | Size / line height | Weight |
|---|---|---|---|
| Body, tables | Inter, falling back to the system sans-serif | 14 / 20 px | 400 |
| Numbers in tables | Same face with tabular numerals enabled | 14 / 20 px | 400; totals 600 |
| Table headers, labels | Same | 12 / 16 px, sentence case | 600 |
| Page title | Same | 20 / 28 px | 600 |
| Report headline figures | Same | 28 / 36 px | 600 |
| Calculation sentence | Same | 16 / 24 px | 500 |

No text below 12 px. Text can be zoomed to 200% without loss of content or function on a display 1280 px wide or wider; at that zoom (640 px of layout width) the work screens stack their panes into one column and keep every control.

## 5. Colour

| Token | Hex | Used for | Contrast (calculated) |
|---|---|---|---|
| `ink` | `#1B2430` | Text | 15.65:1 on white; 14.45:1 on `surface` |
| `ink-muted` | `#51606F` | Secondary text | 6.46:1 on white; 5.96:1 on `surface` |
| `surface` | `#F4F6F8` | Page background | — |
| `card` | `#FFFFFF` | Panels, tables | — |
| `border` | `#6B7785` | Input borders, focus-independent outlines | 4.56:1 on white; 4.21:1 on `surface` |
| `focus` | `#1F5FBF` on light surfaces; `#FFFFFF` on the dark `approved` banner | Focus ring | 6.09:1 on white; white on `#1B2430` is 15.65:1. `primary` on the dark banner would be 2.57:1, so it is not used there |
| `primary` | `#1F5FBF` | Primary buttons, links, selected-line outline | 6.09:1 on white |
| `matched` | `#1B6E3C` on `#E6F4EA` | Matched status | 5.53:1 |
| `exception` | `#B3261E` on `#FDECEA` | Quantity, price, duplicate exceptions | 5.72:1 |
| `absent` | `#7A4A00` on `#FFF4DC` | Receipt absent, unverified | 6.85:1 |
| `draft` | `#5B3FA6` on `#EFEAFB` | Draft, pending approval, suggestion | 6.59:1 |
| `approved` | `#FFFFFF` on `#1B2430` | Approved banner | 15.65:1 |

Rules: green is used only for a line that passed every check. Waived uses `ink-muted` on `surface` with the word "Waived". Favourable price differences are neutral, not green. `#8A94A0` on white (3.08:1) is allowed only for non-text decoration.

## 6. Components

| Component | Behaviour |
|---|---|
| Status chip | Icon + word + colour. Words are fixed: Matched, Exception, Receipt absent, Pending approval, Waived, Needs review, Draft, Approved, Superseded |
| Data table | Sticky header, sortable columns announced with `aria-sort`, row selection by checkbox and `X`, keyboard row focus, column totals where money is summed |
| Evidence pane | PDF canvas with page controls, zoom, a text alternative listing extracted values for the selected line, and "Open original" |
| Calculation sentence | Generated from the same values the rule engine used; never typed by hand |
| Totals bar (batches) | Six segments with counts; the counts are text, the bar is decoration |
| Resolution bar | Radio group of resolution codes, required note for waivers, primary button. Shows "Needs controller approval" before submitting when the value is above the limit |
| Confirm dialog | Title is the action, body restates object and value, focus starts on the safe button, `Esc` cancels |
| Banner | Page-level: connection lost, results updated, report out of date. One at a time; dismissible unless it blocks work |
| Toast | Only for confirmations that need no action; 6 seconds; also written to a status region |
| Form field | Label above, hint below, error below in words with an icon; error summary at the top of the form |
| Worked example | In the alias form: recomputes on each keystroke |

## 7. Interaction feedback and microcopy

| Moment | Copy |
|---|---|
| **Pending operation** (batch on S-06) | "Reading 240 files. 131 ready, 9 need review, 2 failed, 98 still in progress. You can leave this page; nothing will be lost." |
| Pending operation (S-04) | "Reading purchase orders from QuickBooks: 412 so far." |
| **Recoverable error** (S-05) | "37 rows could not be used. 1,184 rows are ready to import. Download the 37 rows with reasons, fix them in your spreadsheet and upload them again, or import the valid rows now." |
| Recoverable error (S-06 file) | "This PDF is password-protected. Remove the password and upload it again." |
| Recoverable error (connection) | "Connection lost. Your last change was saved at 10:42. Trying again…" |
| Conflict | "Dana resolved this exception a moment ago as 'Confirmed short shipment'. Your note is kept below if you want to add it." |
| **Human approval** (S-12 waiver) | Title: "Approve waiver". Body: "You are waiving CAD 168.00 on Fictional Supplier T invoice INV-01042, line 3: invoiced 40 more than received. Sam's reason: 'Second pallet arrived 2 Nov, slip missing.' This will be listed in the report as waived, with your name." Buttons: "Return to Sam", "Approve waiver". |
| Human approval (S-12 conversion) | "Approve conversion: 1 CS of Fictional Supplier T code TS-2x4-8 = 12 EA of 2X4-8-SPF. Example from invoice INV-01042: 5 CS at 50.40 becomes 60 EA at 4.20. 23 lines will be re-matched." |
| Human approval (S-13 report) | "Approve version 2 of the October back-test. Findings CAD 1,912.40, of which not received CAD 1,260.00. Unverified because no receiving evidence: CAD 47,050.00 on 209 lines. 6 exceptions are still open and will be listed as open. Approved figures cannot be changed; later corrections create a new version." |
| Receipt absent, not received (S-09) | "Your receiving log covers this order (1 Sep to 31 Oct) and shows nothing for this line. CAD 420.00 was invoiced. This is listed as 'not received' unless you attach receiving evidence or tie a credit note." |
| Receipt absent, no evidence (S-09) | "No receiving evidence covers this purchase order. MatchDesk cannot say whether the goods arrived. Attach a warehouse record or a delivery document your receiver signed. If you know the goods never came, your controller can confirm that." |
| Supplier slip only (S-09) | "This packing slip comes from the supplier and has no receiver's signature or count. It is shown for reference and is not counted as a receipt." |
| Session about to end | "You will be signed out in 2 minutes because there has been no activity. Stay signed in?" Buttons: "Sign out now", "Stay signed in". |
| Empty queue | "No open exceptions for October. 1,932 of 2,144 lines matched." |
| Refund calculation (S-13) | "Qualifying discrepancies in the governing version: CAD 0.00. Your pilot terms refund the CAD 500 fee when this is below CAD 500.00. Refund applies. Not checked because no receiving evidence was supplied: CAD 48,310.00 on 212 lines." |

All names, document numbers and amounts above are synthetic.

Timing: a spinner appears only after 400 ms; operations longer than 10 seconds show counts or a progress statement; nothing auto-dismisses if it contains an error.

## 8. Evidence, correction, and draft versus approved

**Inspecting source evidence.** From any figure in the report, one click reaches the list behind it; from any list row, one click reaches S-09; in S-09 the invoice line is outlined on the page and each receipt shows file and row. From a receipt, "Open source" shows the spreadsheet row or the packing-slip image. The path is the same in reverse through breadcrumbs.

**Correcting a suggestion.** Extracted values carry a "read" tag. Editing a value changes the tag to "edited" and re-runs the arithmetic check at once. The original reading stays available from a "History" button beside the field, which works with keyboard and touch; it is not shown on hover only. Alias suggestions are cards with "Use this" buttons; choosing one fills the form but nothing is saved until "Confirm alias". A returned approval reopens the clerk's form with the controller's note above it.

**Draft versus approved.**

| State | Banner | Body | Export |
|---|---|---|---|
| Draft | Violet, "DRAFT · version 2 · figures may change" | Figures live | Watermark "DRAFT" on each page; CSV first row says DRAFT |
| Approved | Dark, "APPROVED by Priya N. on 12 Nov 2026 · version 2" | Figures frozen | No watermark; footer shows version and approval |
| Superseded | Grey, "SUPERSEDED by version 3" with link | Frozen | Watermark "SUPERSEDED" |

Line-level: Matched, Exception, Waived and Pending approval are never merged in totals; the report has a row for each.

## 9. Vocabulary

One word per thing, used in navigation, headings, buttons and emails.

| Use | Do not use |
|---|---|
| Invoice, credit note | Bill (reserved for the QuickBooks record: "QuickBooks bill") |
| Purchase order, PO | Order |
| Receiving record, receipt line | Item receipt (a QuickBooks Desktop term) |
| Receipt absent | Missing, unmatched, no GRN |
| Exception | Error, issue, mismatch (except in sales copy) |
| Finding (a discrepancy the rules raised and no evidence removed; "confirmed" is a separate column) | Savings, recovery |
| Not received (the log covers the order and shows nothing) | Missing, lost |
| Receiving evidence: warehouse record, signed delivery document | Proof of delivery (for a supplier's unmarked slip) |
| Unverified | Unmatched, unknown |
| Waive, waived | Ignore, dismiss, accept |
| Alias | Mapping, cross-reference |
| Matched | OK, passed, approved (approved is for people's decisions) |

## 10. Responsive behaviour

| Layout width (CSS px) | Behaviour |
|---|---|
| 1440 and up | Three panes side by side in S-09; full tables |
| 1024–1439 | S-09: document left, data stacked right; tables hide low-priority columns behind a "Columns" control |
| 640–1023 | Every screen keeps every function. S-07 and S-09 stack into one column: calculation and resolution controls first, then purchase order, receipts, and the document in a collapsible region. S-08 shows each exception as a card with the same actions; bulk selection stays. S-05 and S-06 upload and mapping work in one column. This is the width a 1280 px display gives at 200% zoom and a 1366 px laptop gives at 213% |
| 320–639 | Fully supported (eleven screens): S-01, S-02, S-03, S-04, S-12, S-13, S-14, S-16, S-17, S-18, S-19 as single-column cards. **Not fully supported (eight screens):** S-05, S-06, S-07, S-08, S-09, S-10, S-11, S-15 remain readable and show "Open in a wider window to work on this" on their editing controls |

Content reflows at 320 px wide for the fully supported screens without two-direction scrolling, except data tables and the PDF, which scroll inside their own region.

**Known gap against WCAG 2.2 AA.** Between 320 and 639 px of layout width the eight work screens listed above lose their editing functions. That fails SC 1.4.10 Reflow for those screens: the exception for two-dimensional content covers their tables and the PDF, not their controls. It affects a clerk who needs more than 200% zoom on a 1280 px display, or 400% on any display. SC 1.4.4 Resize Text (200%) is met on displays 1280 px wide or wider. The gap is accepted for the pilot and is to be closed before general release; it is not hidden by calling those widths unsupported.

## 11. Accessibility

Target: WCAG 2.2 level AA on every screen, with the one known gap stated in section 10. A target is not a result; every check below is `Not run`.

| Criterion | Applies to | Manual check |
|---|---|---|
| 1.1.1 Non-text content | S-09, S-07 PDF panes | With the PDF pane hidden, the selected line's extracted values are available as text; status icons have text |
| 1.3.1 Info and relationships | All tables; forms | Screen reader announces column headers for each cell in S-08; field labels and error text are associated |
| 1.4.1 Use of colour | Status chips, totals bar | View S-08 and S-13 in greyscale: every status still distinguishable by word and icon |
| 1.4.3 Contrast (minimum) | All text | Measure each token pair on built screens; minimum 4.5:1 |
| 1.3.5 Identify input purpose | S-01 email field, S-02 name, S-16 invite email | Fields carry the matching autocomplete purpose; a browser offers the saved value |
| 1.4.4 Resize text | All screens | On a 1280 px display at 200% zoom, complete one exception on S-09, one correction on S-07 and one upload on S-06: nothing lost |
| 1.4.10 Reflow | S-01, S-02, S-03, S-04, S-12, S-13, S-14, S-16, S-17, S-18, S-19 | At 320 px width: no loss of content or function, no two-direction scrolling. For the eight work screens: record the known gap of section 10 |
| 1.4.13 Content on hover or focus | Field history, tooltips | Nothing is available on hover only; hover content can be dismissed and does not vanish while pointed at |
| 1.4.11 Non-text contrast | Input borders, focus ring, selected-line outline | Minimum 3:1 against adjacent colours |
| 2.1.1 Keyboard, 2.1.2 No keyboard trap | S-08, S-09, S-07, S-05 mapping | Triage 10 exceptions from S-08 through S-09 and back without a pointer; leave the PDF pane with `Tab` and `Esc` |
| 2.2.1 Timing adjustable | Session idle limit on every screen | Leave S-07 idle: a dialog appears 2 minutes before sign-out, is announced, takes focus, and "Stay signed in" extends the session; repeat 10 times. The absolute limit is 24 hours, longer than the 20 hours above which the criterion makes an exception |
| 2.4.2 Page titled | Every route | Title follows "<object> · <screen> · MatchDesk" and changes on route change |
| 2.1.4 Character key shortcuts | S-08, S-09 single-key shortcuts | Shortcuts are inactive while a text field has focus and can be turned off in the user menu |
| 2.4.3 Focus order, 2.4.7 Focus visible | All | Focus ring 2 px with 2 px offset, `primary` on light surfaces and white on the dark banner, is visible on every control, including table rows. Focus lands where [App-flow.md section 5](App-flow.md#5-browser-behaviour) says after a route change, a closed dialog, "Resolve and next" and Back |
| 2.4.11 Focus not obscured (minimum) | S-09 with fixed resolution bar; S-08 sticky header | Tab through the page: the focused control is never fully hidden by a fixed bar |
| 2.5.7 Dragging movements | Pane dividers in S-09; file drop in S-06 | Dividers move with arrow keys and buttons; files can be chosen with a button |
| 2.5.8 Target size (minimum) | Row actions, chips that act as buttons | At least 24 × 24 px |
| 3.2.6 Consistent help | Header on every signed-in screen | The "Help and contact" link is in the same place in the user menu on every screen |
| 3.2.2 On input | Filters in S-08 | Changing a filter updates the list but does not move focus |
| 3.3.1 Error identification, 3.3.3 Error suggestion | S-05 mapping and validation, S-07, S-11, S-15 | Submit S-05 with a missing required column: focus moves to the error summary; each error names the field and the fix; activating an error moves focus to the field |
| 3.3.4 Error prevention (financial) | S-12 approvals, S-13 approval, S-11 retire, S-04 disconnect | Each has a review dialog restating the decision; waivers and resolutions can be reopened |
| 3.3.7 Redundant entry | S-05 mapping, S-11 | A saved column mapping is pre-applied; supplier code and description are pre-filled when coming from S-09 |
| 3.3.8 Accessible authentication (minimum) | S-01 | Sign-in needs only an email address and a link; no puzzle or memorised secret |
| 4.1.2 Name, role, value | Custom table rows, pane dividers, chips | Inspect with a screen reader: role and state announced |
| 4.1.3 Status messages | S-06 totals, S-04 sync, S-09 "Matching…", S-13 "Generating", toasts | With a screen reader running, start a batch: the screen refreshes counts every 5 seconds, but changes are announced through a polite live region at most every 15 seconds; completion and errors are announced once; focus does not move |

After an asynchronous operation ends with an error (failed sync, failed export), the message appears in a banner with `role="alert"` and focus stays where the user is; the banner has a link to the place where the error can be fixed.

## 12. Print and export

The approved report prints on Letter and A4 from the same layout: summary cards become a table, links become footnoted document numbers, every page carries the account name, period, version, status and page number. CSV exports use ISO dates, a dot as decimal separator, and no thousands separators.

**Accessibility of the export.** The on-screen report and the CSV are the accessible forms and carry everything the PDF does. The PDF export is required to be tagged: document title and language set, headings in order, table header cells marked, reading order matching the visual order, and the status (DRAFT, APPROVED, SUPERSEDED) present as text, not only as a watermark. Planned check A11Y-06. If tagging cannot be delivered for the pilot, that is to be recorded as a gap here, not left unstated.
