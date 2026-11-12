# MatchDesk web UI: design system and screenshots (B6, 2026-11-12; B8, 2026-11-13)

The B6 redesign of `web/` replaced the B4 look (top navigation, generic panels) with one design system and one component library. Behaviour, routes and API calls are unchanged; screen states are in [App-flow.md section 7](../App-flow.md#7-as-built-in-b4-2026-11-12). Every screenshot shows the invented demo tenant only (`make seed-demo --preload` on Playwright's own database `matchdesk_e2e`).

## 1. Direction

A mature accounts-payable tool where the arithmetic is the hero. The chrome stays quiet (graphite neutrals, hairline borders, one petrol accent) so that money columns, quantity differences and the calculation sentence are what the eye finds first. Colour carries meaning only: green for a line that passed every check, red for an excess, amber for missing evidence, violet for work waiting on a person (design.md section 5), and every colour comes with a word and an icon.

## 2. Tokens (`web/src/styles/tokens.css`)

| Group | Values |
|---|---|
| Brand (one colour) | Petrol `--brand-50` #eef6f6 to `--brand-800` #0c4144; primary action `--accent` #176669 (6.7:1 with white) |
| Neutrals | Graphite `--gray-0` #ffffff to `--gray-900` #151a21; muted text `--gray-500` #5f6874 (5.0:1 or better on every light surface) |
| Semantic | success #11724c on #e6f4ed, warning #8f5200 on #fdf3e0, danger #b42a20 on #fcebe9, info #2a5bb5 on #eaf0fb, review #5f3dc4 on #f1edfc (all at least 5.2:1) |
| Spacing | 4/8 px scale: `--s-1` 4 px to `--s-12` 48 px |
| Type | Inter Variable; 12/16, 13/18, 14/20 (body), 16/24, 20/28, 24/32 (page title), 30/36 (figures); money and quantities in tabular, slashed-zero figures (`.num`, `.money`) |
| Radii | 4, 6, 8, 12 px and pill |
| Elevation | `--shadow-xs` to `--shadow-lg` (overlays only use the large one) |
| Focus | 2 px petrol outline, 3 px ring on controls (`--focus-ring`) |
| Themes | Light by default; dark follows the device or the user menu (`data-theme`), with every token redefined |

## 3. Components (`web/src/components/`, exported from `index.ts`)

| Component | File | Notes |
|---|---|---|
| Button (primary, secondary, ghost, danger, link; sm, md, lg; loading; disabled reason), IconButton | `Button.tsx` | IconButton's label is its name and tooltip |
| Field, Input, Select, Checkbox | `Form.tsx` | Label, hint and error wired with `aria-describedby` |
| Badge, StatusPill (`StatusChip`) | `Badge.tsx` | One status table (DD-03); lucide icon plus word |
| Card, StatCard | `Card.tsx` | |
| DataTable | `DataTable.tsx` | Sticky header, sorting with `aria-sort`, row hover, selection with select-all, right-aligned money, skeleton and empty state, scrolls inside its own focusable region, stacks into labelled cards under 640 px (`stack-sm`) |
| Tabs | `Tabs.tsx` | ARIA tabs with arrow keys |
| Dialog, Drawer | `Overlay.tsx` | Native `<dialog>`, focus on the safe button, Escape closes, focus returns |
| Toast | `Toast.tsx` | Polite live region, six seconds, at most three |
| Tooltip | `Tooltip.tsx` | Hover and keyboard focus, Escape hides |
| Breadcrumbs, PageHeader, Pagination, Stepper | `Page.tsx` | Focus lands on the page title after navigation |
| FileDropzone | `FileDropzone.tsx` | A real file input inside, so keyboard users choose files the ordinary way |
| EmptyState, Skeleton, TableSkeleton, ErrorPanel | `States.tsx` | Skeletons appear after 400 ms only |

Icons: `lucide-react` 0.468.0 (pinned). Screens still import the B4 names (`PageHead`, `StatusChip`, `Empty`, `Loading`, `Banner`) from `components/ui.tsx`, which now delegates to the library. Tests: `web/src/components/library.test.tsx` (22 tests).

## 4. App shell

Collapsible left sidebar grouped by job: **Work** (Exceptions with the open count, Invoices, Intake, Receiving), **Review** (Approvals with the waiting count, Reports), **Setup** (Getting started, QuickBooks, Aliases, Tolerances, Users, Audit log), filtered by role. Counts are read by screen readers as a description, so link names stay exact. Top bar: company (switcher when the person has several), period selector (the test month the screens default to; held in memory, nothing in browser storage), QuickBooks status, user menu (shortcuts, theme, help, sign out). Content is capped at 1320 px; the match and review screens use 1680 px. Under 1024 px the sidebar becomes a drawer behind a menu button.

## 5. Key screens

- **Sign in**: centred card with the product mark (a ledger with a tick), one field, the one-time-link explanation.
- **Onboarding**: stepper with a progress bar and the current step highlighted; each step's action is a button.
- **Exception queue**: four coverage figures (receipt coverage with a meter, not received, unverified, complete warehouse log), type filters as counters, a filter toolbar with keyboard hints (J, K, Enter, X), a bulk action bar that appears only when rows are selected and says when types are mixed, and a table that stacks into cards on a phone.
- **Match view**: three panes: the PDF (fit to width, zoom and download as icon buttons), the calculation sentence with a line comparison whose difference column is red for an excess and green when within the order or receipts (computed exactly from the stored values, `lib/decimal.ts` `subtract`), receipts and history, and an action panel with the value, the resolution form, and the purchase-order facts.
- **Back-test report**: summary figure cards, findings tables, the approval in a dialog with the reviewed-waivers checkbox.
- **Intake**: drag-and-drop zone and one progress row per file while uploading; batch totals that always add up.

## 6. Screenshots (`docs/screenshots/`)

Captured by `cd web && SHOTS=after npx playwright test -c playwright.shots.config.ts` (before: the same harness on commit 2e99ddb). Since B7 the harness runs on its own stack profile (database `matchdesk_shots`, API 8103, web 5175, its own Mailpit on 1027/8027), separate from Playwright's tests (`matchdesk_e2e`, 8102, 5174, Mailpit 1026/8026); neither touches `matchdesk_dev` or the owner's Mailpit. B7 refreshed every "after" screenshot: S-03 now shows the pilot terms, S-06 the "Invoices by email" panel with one held message, S-07 the line editor, S-13 section 7 the pilot record, S-16 the support-access panel, S-17 the audit log in words.

| Screen | 1440 x 900 | 375 x 812 |
|---|---|---|
| S-01 Sign in | [before](screenshots/before/01-sign-in-desktop.png), [after](screenshots/after/01-sign-in-desktop.png) | [before](screenshots/before/01-sign-in-mobile.png), [after](screenshots/after/01-sign-in-mobile.png) |
| S-03 Onboarding checklist | [before](screenshots/before/02-onboarding-desktop.png), [after](screenshots/after/02-onboarding-desktop.png) | [before](screenshots/before/02-onboarding-mobile.png), [after](screenshots/after/02-onboarding-mobile.png) |
| S-08 Exception queue | [before](screenshots/before/03-exceptions-desktop.png), [after](screenshots/after/03-exceptions-desktop.png) | [before](screenshots/before/03-exceptions-mobile.png), [after](screenshots/after/03-exceptions-mobile.png) |
| S-09 Match view | [before](screenshots/before/04-match-view-desktop.png), [after](screenshots/after/04-match-view-desktop.png) | [before](screenshots/before/04-match-view-mobile.png), [after](screenshots/after/04-match-view-mobile.png) |
| S-09 Invoices list | [before](screenshots/before/05-invoices-desktop.png), [after](screenshots/after/05-invoices-desktop.png) | [before](screenshots/before/05-invoices-mobile.png), [after](screenshots/after/05-invoices-mobile.png) |
| S-06 Invoice intake | [before](screenshots/before/06-intake-desktop.png), [after](screenshots/after/06-intake-desktop.png) | [before](screenshots/before/06-intake-mobile.png), [after](screenshots/after/06-intake-mobile.png) |
| S-06 Intake batch | [before](screenshots/before/07-batch-desktop.png), [after](screenshots/after/07-batch-desktop.png) | [before](screenshots/before/07-batch-mobile.png), [after](screenshots/after/07-batch-mobile.png) |
| S-07 Extraction review | [before](screenshots/before/08-review-desktop.png), [after](screenshots/after/08-review-desktop.png) | [before](screenshots/before/08-review-mobile.png), [after](screenshots/after/08-review-mobile.png) |
| S-05 Receiving imports | [before](screenshots/before/09-receiving-desktop.png), [after](screenshots/after/09-receiving-desktop.png) | [before](screenshots/before/09-receiving-mobile.png), [after](screenshots/after/09-receiving-mobile.png) |
| S-05 Receiving import | [before](screenshots/before/10-receiving-import-desktop.png), [after](screenshots/after/10-receiving-import-desktop.png) | [before](screenshots/before/10-receiving-import-mobile.png), [after](screenshots/after/10-receiving-import-mobile.png) |
| S-11 Aliases | [before](screenshots/before/11-aliases-desktop.png), [after](screenshots/after/11-aliases-desktop.png) | [before](screenshots/before/11-aliases-mobile.png), [after](screenshots/after/11-aliases-mobile.png) |
| S-04 QuickBooks connection | [before](screenshots/before/12-quickbooks-desktop.png), [after](screenshots/after/12-quickbooks-desktop.png) | [before](screenshots/before/12-quickbooks-mobile.png), [after](screenshots/after/12-quickbooks-mobile.png) |
| S-12 Approvals | [before](screenshots/before/13-approvals-desktop.png), [after](screenshots/after/13-approvals-desktop.png) | [before](screenshots/before/13-approvals-mobile.png), [after](screenshots/after/13-approvals-mobile.png) |
| S-13 Back-test reports list | [before](screenshots/before/14-reports-desktop.png), [after](screenshots/after/14-reports-desktop.png) | [before](screenshots/before/14-reports-mobile.png), [after](screenshots/after/14-reports-mobile.png) |
| S-13 Back-test report | [before](screenshots/before/15-report-desktop.png), [after](screenshots/after/15-report-desktop.png) | [before](screenshots/before/15-report-mobile.png), [after](screenshots/after/15-report-mobile.png) |
| S-15 Tolerances | [before](screenshots/before/16-tolerances-desktop.png), [after](screenshots/after/16-tolerances-desktop.png) | [before](screenshots/before/16-tolerances-mobile.png), [after](screenshots/after/16-tolerances-mobile.png) |
| S-16 Users and support access | [before](screenshots/before/17-users-desktop.png), [after](screenshots/after/17-users-desktop.png) | [before](screenshots/before/17-users-mobile.png), [after](screenshots/after/17-users-mobile.png) |
| S-17 Audit log | [before](screenshots/before/18-audit-desktop.png), [after](screenshots/after/18-audit-desktop.png) | [before](screenshots/before/18-audit-mobile.png), [after](screenshots/after/18-audit-mobile.png) |
| Settings index (links to S-03, S-04, S-15 to S-17) | [before](screenshots/before/19-settings-desktop.png), [after](screenshots/after/19-settings-desktop.png) | [before](screenshots/before/19-settings-mobile.png), [after](screenshots/after/19-settings-mobile.png) |
| S-14 Weekly summary (B7) | [after](screenshots/after/22-weekly-desktop.png) | [after](screenshots/after/22-weekly-mobile.png) |
| S-18 Operator console (B7) | [after](screenshots/after/23-operator-console-desktop.png) | [after](screenshots/after/23-operator-console-mobile.png) |
| S-18 Account: pilot record, billable units, support access (B7) | [after](screenshots/after/24-operator-account-desktop.png) | [after](screenshots/after/24-operator-account-mobile.png) |
| S-08 and S-09 in dark theme | [exceptions](screenshots/after/20-exceptions-dark-desktop.png), [match view](screenshots/after/21-match-view-dark-desktop.png) | |

## 6a. B7 screens

S-14, S-18 and the new panels use the same components and tokens: figure cards (the first card carries the finding tint, as on S-13), stacked-card tables under 640 px, the form grid of S-15 for the pilot record, `grant-row` blocks for support requests, and a violet support banner (`--review-*` tokens) on every screen while an operator reads an account. The S-07 line editor replaces the wide lines table with one block per line (supplier code and description, then quantity, unit, unit price and amount), so the arithmetic fields never leave the pane.

## 6b. B8 role-based redesign (2026-11-13)

The same tokens and components; layout and interaction changed around the decisions each role makes. Before and after captures on the same seeded records and viewports are in [screenshots/b8/](screenshots/b8/README.md) (state log, measurements).

- **Direction kept, one element added.** The arithmetic is still the hero; B8 makes it a ledger line on S-09: billed − received = excess × unit price = exposure, each operator on the border between two figures, the received figure linked to its receiving row. Strong colour stays for the exposure, primary actions and state that changes a decision; an open row in the queue carries no status badge (the queue is what is open), only pending approval, resolved or waived do.
- **Levels.** Page title; decision summary (ledger, approval's proposed change at 24 px, validation counts at 30 px, the role's next task on S-03); source evidence (PDF, receipts, affected records); secondary metadata in 12 to 13 px muted text. Money and quantities are right-aligned in tables with tabular figures, left-aligned in the ledger where each figure stands alone.
- **S-08.** Scope chips (dates, supplier, type, status, value range), each removable; filters in a compact bar (behind **Filters** under 640 px); type tabs with counts; the list with invoice and supplier, why it needs you, PO and item, quantity difference, amount and **Review**; the server's count and value for the whole scope in the footer. Coverage and "why counts differ" are collapsed below the list. Under 640 px each exception is a case block (document and amount, reason, supplier and PO, **Review**).
- **S-09.** Ledger, then document, calculation and action panes (stacked under 1280 and 1024 px); "Exception queue: <scope>" crumb; Previous, position, Next from the server; the decision's consequence before submission; PDF **Fit width** and expanded view.
- **S-12.** One card per request in four columns: proposed change, affected records, "If you approve", decision.
- **S-13.** "Next decision" or "Governing version" line on the list; **Governing** tag; flagged, confirmed and recovered as three separate figures.
- **S-05, S-06, S-07, S-03, S-17, S-18.** Validation counts lead; a read batch leads with "Review N invoices"; total check row (printed, lines plus tax, field, result); next task first; who changed what first; account at a glance first.
- **Shell.** "QuickBooks: demo data" with a blue dot in recorded-response mode; the sidebar's Exceptions link returns to the last queue opened; the support banner is sticky under the top bar.

| Screen | 1440 x 900 | 1024 x 768 | 375 x 812 |
|---|---|---|---|
| S-08 Exception queue | [before](screenshots/b8/before/01-queue-1440.png), [after](screenshots/b8/after/01-queue-1440.png) | [before](screenshots/b8/before/01-queue-1024.png), [after](screenshots/b8/after/01-queue-1024.png) | [before](screenshots/b8/before/01-queue-375.png), [after](screenshots/b8/after/01-queue-375.png) |
| S-09 FF-1003 | [before](screenshots/b8/before/02-ff1003-1440.png), [after](screenshots/b8/after/02-ff1003-1440.png) | [before](screenshots/b8/before/02-ff1003-1024.png), [after](screenshots/b8/after/02-ff1003-1024.png) | [before](screenshots/b8/before/02-ff1003-375.png), [after](screenshots/b8/after/02-ff1003-375.png) |
| S-12 CT-25 conversion | [before](screenshots/b8/before/03-approval-1440.png), [after](screenshots/b8/after/03-approval-1440.png) | [before](screenshots/b8/before/03-approval-1024.png), [after](screenshots/b8/after/03-approval-1024.png) | [before](screenshots/b8/before/03-approval-375.png), [after](screenshots/b8/after/03-approval-375.png) |
| S-14 Weekly summary | [before](screenshots/b8/before/04-weekly-1440.png), [after](screenshots/b8/after/04-weekly-1440.png) | [before](screenshots/b8/before/04-weekly-1024.png), [after](screenshots/b8/after/04-weekly-1024.png) | [before](screenshots/b8/before/04-weekly-375.png), [after](screenshots/b8/after/04-weekly-375.png) |
| S-14 to S-08 drill-down | [before](screenshots/b8/before/05-weekly-to-queue-1440.png), [after](screenshots/b8/after/05-weekly-to-queue-1440.png) | | |
| S-18 Operator account | [before](screenshots/b8/before/06-operator-account-1440.png), [after](screenshots/b8/after/06-operator-account-1440.png) | | |
| Dark theme, with the invoice PDF | [queue before](screenshots/b8/before/01-queue-dark-1440.png), [after](screenshots/b8/after/01-queue-dark-1440.png); [FF-1003 before](screenshots/b8/before/02-ff1003-dark-1440.png), [after](screenshots/b8/after/02-ff1003-dark-1440.png) | [FF-1003 after](screenshots/b8/after/02-ff1003-dark-1024.png) | [queue after](screenshots/b8/after/01-queue-dark-375.png), [FF-1003 after](screenshots/b8/after/02-ff1003-dark-375.png) |

## 7. Accessibility checks

axe-core (WCAG 2.0 to 2.2 A and AA, serious and critical fail the run) on sign-in, batch, extraction review, exception queue, match view, approvals and report in `web/e2e/full-flow.spec.ts`, and on the operator console, weekly summary and intake with email in `web/e2e/pieces-b7.spec.ts`; the phone-width test fails if any of nine reading screens (with a back-test report) scrolls sideways or shows a list table that is not stacked into cards, and `tablesFit` fails if a table is wider than its box at 1440 px (exception queue, extraction review, report, audit log, weekly summary). B8 adds `web/e2e/queue-b8.spec.ts`: the first case's Review control is inside the 375 x 812 viewport, not covered and opens the case; axe on the queue opened from the weekly summary.
