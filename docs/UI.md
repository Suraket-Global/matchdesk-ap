# MatchDesk web UI: design system and screenshots (B6, 2026-11-12)

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

Captured by `cd web && SHOTS=after npx playwright test -c playwright.shots.config.ts` (before: the same harness on commit 2e99ddb). The harness creates and drops `matchdesk_e2e`; it never touches `matchdesk_dev`.

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
| S-08 and S-09 in dark theme | [exceptions](screenshots/after/20-exceptions-dark-desktop.png), [match view](screenshots/after/21-match-view-dark-desktop.png) | |

## 7. Accessibility checks

axe-core (WCAG 2.0 to 2.2 A and AA, serious and critical fail the run) on sign-in, batch, extraction review, exception queue, match view, approvals and report in `web/e2e/full-flow.spec.ts`; the phone-width test fails if any of five reading screens scrolls sideways and names the element that sticks out.
