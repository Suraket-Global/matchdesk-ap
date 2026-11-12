# AGENTS.md — MatchDesk AP three-way match

Canonical instructions for any coding or documentation agent working in this repository. `CLAUDE.md` adds product-specific guidance and defers to this file.

**State of the repository:** the ten planning documents at the root, plus build milestone B1 (2026-11-11, authorised by the owner before the Phase 0 gate) under `backend/`: the package layout, `core`, the pure `matching` engine, migrations with row-level security, match runs, a minimal API and a worker, with unit and integration tests; and build milestone B2 (2026-11-11): emailed sign-in links, cookie sessions with anti-forgery tokens, idle and absolute limits, rate limits, invitations, memberships, operator TOTP, mail over SMTP to the local Mailpit inbox and files over the S3 API to local MinIO. Build milestone B3 (2026-11-12, branch `feat/b3-workflows`): every workflow through the real API on the local stack: QuickBooks connection, token sealing and resumable sync over recorded synthetic responses (shape unverified until T-1.1.1), receiving import, invoice intake with a local text-PDF extractor, extraction review, match-run triggers, the exception workflow with approvals, aliases and tolerances, and the back-test report with approval and export; `make seed-demo` loads one invented tenant. Build milestone B4 (2026-11-12, branch `feat/b4-web`): the React web app under `web/` (TRD AD-11) wired to that API, screens S-01 to S-19 (S-14 weekly summary and S-18 operator console say "not built yet"), playable end to end as clerk and controller by following `docs/PLAY.md`; Playwright E2E-01 with axe-core scans runs headless in the installed Chrome. The independent B3/B4 review of 2026-11-12 was fixed on `feat/b4-fixes` (migrations 0014 to 0016; [verification-report-fixing.md section 15](verification-report-fixing.md#15-b3b4-review-fixes-2026-11-12)). B6 polish (2026-11-12, branch `feat/b6-polish`): three outside QA findings fixed with regression tests (the local PDF reader takes the document type from the heading and labelled fields only; Playwright runs on its own database `matchdesk_e2e` with its own API on 8102, worker and web server on 5174, and fails if `matchdesk_dev` changed; the live QuickBooks status is stated plainly), and the web app redesigned on one design system and component library ([docs/UI.md](docs/UI.md); [verification-report-fixing.md section 16](verification-report-fixing.md#16-b6-polish-2026-11-12)). Nothing is deployed; there is no real QuickBooks, extraction, mail or storage provider (Intuit and the hosted extractor are selected by settings and refuse to run unconfigured). **The live QuickBooks connection is not built and must not be faked:** `IntuitQboReader.page()` raises `QboNotConfiguredError` on purpose. It needs the owner's Intuit developer account and the sandbox check T-1.1.1; the step that remains is that check, then the live reader written from its recorded responses (TODO list in `TRD.md` section 11). What ran, and how, is in [verification-report-fixing.md sections 9](verification-report-fixing.md#9-build-milestone-b1-2026-11-11), [10](verification-report-fixing.md#10-build-milestone-b2-sign-in-and-local-services-2026-11-11), [13](verification-report-fixing.md#13-b3-workflows-2026-11-12) and [14](verification-report-fixing.md#14-b4-web-app-2026-11-12). Commands marked **exists** in section 12 work locally; all others are still **proposed**. Round C2 (2026-11-11) added `compliance/self-check.md`: the business's own reading of the legal rules (not legal advice), with checklists, templates and red lines; by owner decision no lawyer is used for now and the gates that waited on one point to that file.

## 1. Reading order

1. `Decision.md` — why this might be worth building, the economics, the stop rule, sources.
2. `PRD.md` — must-haves MH-01 to MH-16 and what is deliberately out.
3. `App-flow.md` — screens S-01 to S-19 and their states.
4. `design.md` — how the screens look and behave; vocabulary.
5. `schema.md` — tables, permissions, tenant boundary, migrations.
6. `TRD.md` — stack, modules, runtime, API, match rules, threat model.
7. `execution-plan.md` — phases, tasks, tests.
8. `verification-report-fixing.md` — what is checked, the trace matrix, the risk register, findings.

## 2. Sources of truth

| Subject | Authoritative file | Others must not restate, only cite |
|---|---|---|
| Buyer, price, economics, stop rule, sources | `Decision.md` | Numbers are quoted with their label |
| Requirements and acceptance criteria | `PRD.md` | Cite `MH-nn` |
| Screens, routes, states | `App-flow.md` | Cite `S-nn` |
| Visual and interaction rules, vocabulary | `design.md` | Cite `DD-nn` |
| Tables, permissions, retention, migrations | `schema.md` | |
| Stack, modules, API, match rule table, quality targets | `TRD.md` | Cite `AD-nn` |
| Tasks and tests | `execution-plan.md` | Cite `T-p.m.t` and test IDs |
| Production risks R-01 to R-22, findings F-nnn, trace matrix | `verification-report-fixing.md` | Cite the ID; never copy a risk row elsewhere |

If two files disagree, the authoritative file wins and the other is corrected in the same change.

## 3. Product boundaries

- The product reads from QuickBooks Online and never writes to it in this version.
- Match decisions and every money calculation are deterministic code. A model reads documents into a fixed schema and nothing else.
- A line with no independent receiving evidence is an exception of type `receipt_absent`. No setting, tolerance, bulk action or refactoring may let it be stored or shown as matched. It may be a finding ("not received") and is never left out of the refund calculation without being shown.
- Independent receiving evidence means class A (warehouse record, including a QuickBooks Online item receipt entered by the receiver before the bill, imported from an export) or class B (receiver-attested delivery document), as defined in `Decision.md` section 3. The QuickBooks "billed against PO" quantity, an item receipt entered by accounts-payable staff or after the bill, and a supplier's unmarked packing slip are context only and never a receipt. The QuickBooks Online API has no item-receipt entity; never add an API read for one.
- Matching uses open-PO history: earlier invoices, bills, credits and receipts on any purchase order a test document names, with no date filter. Document order is date, normalised number, file hash; never upload time.
- The failure ranking is in `Decision.md` section 1; do not restate a different "highest risk" elsewhere.
- Scope is the must-haves in `PRD.md`. Items in PRD section 9 are out until the stated evidence exists. Do not add features, endpoints, tables or screens without a requirement ID (R-21).

## 4. Number and claim discipline

- Every number is labelled `[chat]`, `[source: SRC-nn]` or `[assumption]`. Keep the label when you move or quote a number.
- Do not turn an assumption into a statement of fact. Do not cite a source you did not open; write "unverified, no source consulted".
- If you change an input in `Decision.md`, recompute every result that depends on it and show the arithmetic.
- Examples use synthetic data only. Never add real customer names, documents, prices, credentials or tokens.

## 5. Architecture conventions (for when implementation starts)

- One package, two entry points (`api`, `worker`), module list and import rules as in `TRD.md` section 5. `matching` is pure: no database, no network, no clock except through arguments.
- **Reuse before writing.** Money and rounding: `core.money`. Settings: `core` settings object. Logging and correlation: `core`. Tenant context and permissions: `tenancy`. File keys and access: `blobstore`. Number normalisation and duplicate rules: `matching`. Job state transitions: the shared transition helper. Search these before adding a helper; if you add one, list it in the utilities index kept in this section of this file (R-03, R-06).
- The worker must start without importing any web-framework module (R-07).
- Amounts are `Decimal` and `NUMERIC`. No binary floats in money or quantity code.
- Every mutating endpoint accepts an idempotency key; every editable record carries a version.

Utilities index (B1, B2, B3). Search here before adding a helper:

| Need | Use | File |
|---|---|---|
| Decimal conversion refusing floats; half-up rounding to cents, price or quantity; line amount | `core.dec`, `core.round_cents`, `core.round_price`, `core.round_qty`, `core.line_amount` | `backend/src/matchdesk/core/money.py` |
| Settings (one object for API and worker; reads the environment, then the gitignored `backend/.env`; `fingerprint()` for CI-02 leaves secrets out; `require_secrets()`) | `core.load_settings()` | `core/settings.py` |
| Request-body limits (413 before reading); client address behind trusted proxies | `api.limits.BodyLimitMiddleware`, `api.limits.client_address`, `MAX_FILE_BYTES` | `api/limits.py` |
| Outgoing mail (SMTP: Mailpit locally, a provider later; fake for tests) | `core.Mailer`, `core.SmtpMailer`, `core.RecordingMailer`, `core.mailer_from_settings` | `core/mail.py` |
| JSON logging, correlation ID, field allow-list | `core.configure_logging`, `core.set_correlation_id`, `core.get_logger` | `core/logging.py` |
| Clock | `core.SystemClock`, `core.FixedClock` | `core/clock.py` |
| Errors (404-equivalent, 403, 409, missing tenant) | `core.NotFoundError`, `ForbiddenError`, `ConflictError`, `TenantContextError` | `core/errors.py` |
| Tenant transaction; no-tenant transaction; operator transaction; a user's own memberships across tenants; one invitation by its token hash | `tenancy.session(tenant_id)`, `tenancy.global_session()`, `tenancy.operator_session()`, `tenancy.user_session(user_id)`, `tenancy.invitation_lookup_session(token_hash)` | `tenancy/db.py` |
| Permission table of schema.md 4.1 as data; the one check | `tenancy.PERMISSIONS`, `tenancy.can(role, action)`; in the API `api.common.require(p, action)` | `tenancy/permissions.py`, `api/common.py` |
| Tenant-owned table boilerplate; composite tenant foreign key; column types | `tenancy.TenantMixin`, `tenant_args()`, `tfk()`; `MONEY`, `PRICE`, `QTY`, `enum_check` (exported from `tenancy`) | `tenancy/db.py`, `tenancy/types.py` |
| Compare-and-set state transition (the shared transition helper) | `tenancy.transition()` | `tenancy/transitions.py` |
| Enqueue in the business transaction; claim with lease; job wrapper that refuses no tenant | `tenancy.enqueue`, `tenancy.claim`, `tenancy.run_claimed` | `tenancy/jobs.py` |
| File keys (TRD 8.7 format) and tenant-checked file access over the configured store (local directory or S3/MinIO) | `blobstore.build_key`, `put`, `get`, `delete`, `store()` (`LocalStore`, `S3Store`) | `blobstore/__init__.py` |
| Document and supplier-code normalisation; deterministic document order | `matching.normalise_number`, `normalise_code`, `normalise_uom`, `document_order_key` | `matching/normalise.py` |
| Rule set v1; counting-receipt rule; coverage rule; whether an alias converts; input fingerprint; float refusal | `matching.evaluate`, `receipt_line_counts`, `is_covered`, `alias_converts` (in `engine.py`), `input_fingerprint`, `assert_no_floats` (in `fingerprint.py`) | `matching/engine.py`, `matching/fingerprint.py` |
| Build match inputs from the database (no date filter); request and execute a match run (reuse only while current; per-tenant lock); store results with supersede | `exceptions.build_match_input`, `request_run`, `execute_run`, `store_result` | `exceptions/inputs.py`, `runs.py`, `store.py` |
| Read-time staleness of a stored result; re-match everything that used an alias | `exceptions.stale_runs`, `exceptions.rematch_alias` | `exceptions/runs.py` |
| Who may resolve which exception with which code | `exceptions.check_resolution_allowed` | `exceptions/permissions.py` |
| Audit event inside the business transaction | `audit.write_audit` | `audit/__init__.py` |
| Batch, file intake, lease, completion, batch summary, retry failed | `intake.add_file`, `take`, `complete`, `batch_summary`, `retry_failed` | `intake/service.py` |
| Extraction interface, fake, arithmetic gates | `extraction.Extractor`, `FakeExtractor`, `verification_gates` | `extraction/provider.py` |
| QuickBooks read interface and fake (no write method) | `qbo.QboReader`, `qbo.FakeQboReader` | `qbo/client.py` |
| Refund calculation over exceptions | `reporting.calculate_refund` | `reporting/refund.py` |
| Text-only PDF writer (Courier, optional draft watermark) | `core.text_pdf` | `core/pdf.py` |
| AES-256-GCM sealing with key id (moved to the kernel in B3; `identity.secrets_box` re-exports) | `tenancy.seal`, `tenancy.unseal` | `tenancy/secrets_box.py` |
| `If-Match` parsing, 409 with the current record, idempotency replay and storage, page limit | `api.common.if_match`, `StaleVersion`, `conflict_response`, `idempotent_replay`, `remember`, `body_hash`, `page_limit` | `api/common.py` |
| QuickBooks reader (paged, read only), recorded fixtures, Intuit placeholder | `qbo.QboReader`, `RecordedQboReader`, `FakeQboReader`, `reader_from_settings`, `DEFAULT_FIXTURES` | `qbo/client.py` |
| QuickBooks connection: authorise, callback, refresh, disconnect, "may we process" | `qbo.start_authorization`, `complete_callback`, `access_token`, `disconnect`, `processing_allowed`, `FakeIntuitTokenEndpoint` | `qbo/oauth.py` |
| Sync runs (scope fingerprint, cursor per page, upserts) | `qbo.request_sync`, `execute_sync`, `make_sync_handler` | `qbo/sync.py` |
| Receiving file sniffing and parsing within TRD 8.7 limits | `receiving.sniff_receiving`, `read_table` | `receiving/parse.py` |
| Receiving import: create, declare, map, validate, commit, void, class B confirm, attest, late lines | `receiving.create_import`, `set_declaration`, `save_mapping`, `validate`, `preview`, `commit`, `void`, `confirm_receipt`, `attest`, `approve_late_lines` | `receiving/service.py` |
| Counting receipt totals per PO line for read screens (feeds `matching.receipt_line_counts`) | `receiving.counting_receipt_totals` | `receiving/counting.py` |
| Extraction output to invoice rows; vendor and PO identification | `intake.materialise`, `identify_vendor`, `link_po` | `intake/documents.py` |
| Extraction review: describe with provenance, correct, confirm | `intake.describe_fields`, `correct`, `confirm`, `current_gates` | `intake/review.py` |
| Local text-PDF extractor; extractor from settings | `extraction.local_pdf.LocalPdfExtractor`, `extraction.extractor_from_settings` | `extraction/local_pdf.py`, `extraction/provider.py` |
| Match-run triggers (vendor scope) and the `match_request` job | `exceptions.request_runs`, `related_invoices`, `invoices_on_pos`, `invoices_on_po_lines`, `handle_match_request` | `exceptions/triggers.py` |
| Resolutions, bulk, withdraw, reopen, approvals decision, late-evidence approval | `exceptions.resolve`, `bulk_resolve`, `withdraw`, `reopen`, `decide`, `request_late_receipt_approval`, `po_lines_with_open_exceptions`, `unapproved_waivers` | `exceptions/workflow.py` |
| Aliases (create, retire, suggestions) and versioned tolerances (set, preview) | `exceptions.create_alias`, `retire_alias`, `rematch_for_alias`, `suggestions`, `set_tolerance`, `preview_tolerance` | `exceptions/rules_admin.py` |
| Back-test report: draft, blocking checks, approve, export, refund evaluation | `reporting.create_draft`, `blocking_reasons`, `approve`, `export_pdf`, `export_csv`, `refund_evaluation`, `section_of` | `reporting/backtest.py` |
| Pilot measurement in three separate counts: flagged discrepancy, controller-confirmed overcharge, credit recovered (C1) | `reporting.measure_findings`, `FindingOutcome` | `reporting/outcomes.py` |
| Whether a QuickBooks Online item-receipt export row counts as class A (receiver, before the bill, not accounts-payable staff) (C1) | `receiving.item_receipt_rejection`, `QboItemReceiptRow`, `QBO_ITEM_RECEIPT_SOURCE` | `receiving/qbo_item_receipts.py` |
| Read-side words and evidence for the web screens: queue context, match-view evidence per line (PO line, receipt lines with file, row and class, other documents on the PO line), calculation sentence from stored values, user and vendor names (B4) | `api.views.exception_context`, `line_evidence`, `calculation`, `bill_status`, `user_names`, `vendor_names`, `qty` | `api/views.py` |
| Vendors, items, audit-log list and CSV export endpoints (B4) | `api.read_routes.register_read_routes` | `api/read_routes.py` |
| Headers and first 20 rows of a stored receiving file for the mapping step (B4) | `receiving.file_preview` | `receiving/service.py` |
| Row lock before an `If-Match` comparison; transaction advisory lock on a text key (review M2, M3, m5) | `tenancy.lock_for_update`, `tenancy.advisory_lock` | `tenancy/transitions.py` |
| Live receipt coverage of a period (S-08 strip) | `reporting.live_coverage` | `reporting/backtest.py` |
| Web: same-site path for `?next=` and `?from=`; unit price with cents; an exception that adds nothing on its line | `safePath` (`lib/format.ts`), `price` (`lib/decimal.ts`), `zeroCounted` (`lib/words.ts`) | `web/src/lib/` |
| Web components (B6): Button, IconButton, Field, Input, Select, Checkbox, Badge, StatusPill, Card, StatCard, DataTable, Tabs, Dialog, Drawer, toast, Tooltip, Breadcrumbs, PageHeader, Pagination, Stepper, FileDropzone, EmptyState, Skeleton, TableSkeleton, ErrorPanel; design tokens | `web/src/components/index.ts`; tokens in `web/src/styles/tokens.css` (docs/UI.md) | `web/src/components/` |
| Web: the selected test month (top bar period selector) | `usePeriod`, `PeriodProvider` | `web/src/app/period.tsx` |
| Web: exact decimal difference for display | `subtract` | `web/src/lib/decimal.ts` |
| Document type from heading and labelled fields only (B6) | `extraction.local_pdf.document_type` | `extraction/local_pdf.py` |
| Playwright's own stack (database `matchdesk_e2e`, API 8102, worker; create, seed, drop); row counts of a local database | `backend/scripts/e2e_stack.sh` (`up`, `seed`, `down`), `backend/scripts/db_counts.py`; `web/e2e/stack.ts` | `backend/scripts/`, `web/e2e/` |
| Register every ORM model before the first flush (worker start) | `schema_registry.load_all_models` | `schema_registry.py` |
| Web: decimal strings and integer cents (no floats), extraction checks in words, vocabulary, one HTTP client with anti-forgery token in memory and idempotency keys | `web/src/lib/decimal.ts`, `lib/checks.ts`, `lib/words.ts`, `api/client.ts` | `web/src/` |
| Sign-in links, session lookup and end, anti-forgery token, tenant switch, `/me` | `identity.request_login_link`, `exchange_login_token`, `load_session`, `resolve_session`, `issue_session` (fixtures), `end_session`, `csrf_for`, `csrf_matches`, `switch_tenant`, `describe_me` | `identity/auth.py` |
| Invitations, users and memberships (last-controller guard is a trigger) | `identity.create_invitation`, `list_invitations`, `revoke_invitation`, `accept_invitation`, `list_users`, `update_membership` | `identity/auth.py` |
| Operator TOTP (RFC 6238) and AES-256-GCM sealing with key id | `identity.enroll_operator`, `identity.totp.verify`, `identity.secrets_box.seal` / `unseal` | `identity/totp.py`, `identity/secrets_box.py` |

## 6. Tenant safety

- Tenant comes from the session (API) or the job payload (worker), set once through `tenancy.session()`. Never from a URL, body or cache key supplied by the client.
- Every tenant-owned table ships with `tenant_id`, a row-level security policy, composite foreign keys, and a test that reads it without tenant context and gets zero rows.
- Files are read and written only through `blobstore`. No direct paths, no storage links handed to browsers.
- No server-side cache without a design change recorded in `TRD.md` and R-05 re-examined.
- A cross-tenant request returns "not found", identical to a missing record.
- Operator access needs an active support grant and is audited.

## 7. Migrations

- One linear history; never merge with two heads (R-10).
- Declare every index and constraint in both the migration and the ORM model; keep the manifest of policies, triggers and special indexes current (R-08).
- Expand, then contract in a later release. No down-migrations in production.
- Indexes on existing tables are built concurrently, one per migration; constraints are added not-valid then validated; lock timeout 5 seconds [assumption] (R-11).
- Backfills are resumable batch jobs, never part of a schema migration (R-09).
- Never weaken the check constraints that guard `receipt_absent` and matched lines without changing `PRD.md` MH-07 first; that change needs the founder's decision.
- Every policy that admits the operator setting must be on the allow-list of three tables in `schema.md` section 4.3.

## 8. Tests

- Test IDs and fixtures are in `execution-plan.md` section 7. A change to a match rule must update the golden fixtures and the rule table in `TRD.md` section 8.5 together.
- Rule-engine changes require the unit and property suite. Anything touching queries, jobs or files requires the tenant-isolation tests. Anything touching screens S-08 or S-09 requires the navigation-state and keyboard tests.
- A change to the extraction provider, model or prompt requires the evaluation set to pass first.
- Fixtures are synthetic. Do not copy pilot data into tests.

## 9. What to update when something changes

| If you change | Also update |
|---|---|
| A requirement or acceptance criterion | `PRD.md`; trace matrix in `verification-report-fixing.md`; affected screens in `App-flow.md`; tasks and tests in `execution-plan.md` |
| A screen, route or state | `App-flow.md` inventory and diagram; `design.md` if layout, copy or accessibility mapping changes; API table in `TRD.md`; trace matrix; route and link check |
| A permission or role | Permission table in `schema.md` section 4.1 first (it is the single oracle); then the roles column in `TRD.md` section 12 and the `App-flow.md` inventory so they agree cell for cell; permission tests IT-13 and IT-29; `PRD.md` section 6 if a role's purpose changes |
| A table, column, index or constraint | `schema.md` dictionary, index table and ER diagram; migration and ORM model; trace matrix if a must-have's storage moved |
| A match rule or tolerance default | `TRD.md` section 8.5; `PRD.md` MH-06 to MH-09 examples; golden fixtures; a new `ruleset_versions` row |
| An operating assumption (price, cost, funnel rate, stop rule, hosting) | `Decision.md` with recomputed arithmetic; `TRD.md` operating cost and constraints; `execution-plan.md` gates if thresholds move |
| A task estimate | `execution-plan.md` section 5 totals; the build timeline, start month, ramp tables and troughs in `Decision.md` section 7.5; hour figures quoted in `Decision.md` sections 7.1, 9 and 11 |
| The refund criterion, the evidence classes or the receiving-coverage rule | `Decision.md` sections 3 and 5.1 first; then `PRD.md` MH-03, MH-07, MH-16; `TRD.md` section 8.5; `schema.md` checks; tests UT-16, UT-17, UT-30, IT-17 |
| An accepted security or accessibility gap | The gap tables in `TRD.md` sections 8.1, 8.3, 8.7 and `design.md` section 10; the open-items table in `verification-report-fixing.md` section 7 |
| A source or a verified fact | `Decision.md` section 13 with date consulted, scope and restriction; remove "unverified" only where the source was actually read |
| Stack or deployment | `TRD.md` sections 4 and 7; proposed commands in `execution-plan.md` section 6; this file's section 5 |
| A risk's prevention or test | Only the row in `verification-report-fixing.md` section 5 |
| A legal rule, compliance checklist, template or red line | `compliance/self-check.md` first (with source and date opened); then the gate text in `Decision.md` sections 11 and 12.4, `execution-plan.md` section 2 and Phase 0 tasks, and any screen or retention rule it changes (`App-flow.md`, `schema.md` section 8, `TRD.md`); new sources in `Decision.md` section 13 |

## 10. Git hygiene

- Default branch `main`, protected. Work on `<type>/<task-id>-<slug>`, for example `feat/T-4.1.2-cumulative-match`.
- One task per branch where possible. Delete a branch after merge. Never delete or force-push a branch with unmerged work that is not yours (R-22).
- Commit messages name the task or requirement ID.
- Never commit `.env` files, credentials, tokens, real documents or exports.
- Coordination ledgers, briefs and review scratch files live outside this repository.
- Do not add files to the repository root beyond the ten planning documents until implementation is authorised; then application code goes in subdirectories. The compliance self-check lives in `compliance/`.

## 11. Reporting completion accurately

- Say what was done, what was checked and how, and what was not checked.
- Mark application tests `Not run` until they have run; give the command and result when they have.
- State accepted gaps as gaps. Do not describe a failing width, a missing second factor or an unscanned file as "unsupported" or "out of scope" to make a target read as met.
- "Planned", "proposed" and "designed" are not "done". A control described in a document is not evidence that it works.
- If a source could not be opened, say so. If a number is an assumption, say so.
- Record findings and fixes in `verification-report-fixing.md`; the author records the fix, the reviewer records the retest.
- Do not record commit identifiers inside the repository.

## 12. Proposed commands

See `execution-plan.md` section 6 for purpose, inputs, outputs and failure behaviour. **Exists** means it runs locally since B1 (2026-11-11); the rest are proposed.

| Command (proposed) | Purpose |
|---|---|
| `make up` / `make down` | Start or stop the local stack with health checks. **Exists**: checks PostgreSQL and Redis, migrates `matchdesk_dev`, starts API (port 8101) and worker directly, waits for `/readyz` (database, migrations, file store); needs `backend/.env` (copy `backend/.env.example`; session and token keys, MinIO settings); Mailpit (127.0.0.1:1025, UI 8025) and MinIO (127.0.0.1:9000) must be running; Compose is still proposed |
| `make seed-demo` | **Exists** (B3, changed in B4): loads one invented tenant into `matchdesk_dev` (controller and clerk with `.invalid` addresses, a sync over the recorded QuickBooks fixtures, aliases with one conversion pending, the receiving attestation) and writes the receiving file and 13 invoice PDFs to `play-files/` for the owner to upload (`docs/PLAY.md`); `ARGS=--preload` also uploads and processes them as in B3; `--tag NAME` makes a separate tenant for test runs, writes its files to a temporary folder (`--files-dir` chooses it) and empties the local sign-in counters; refuses in production; a second run changes nothing |
| `make demo-reset` | **Exists** (B4): stops the API and worker, empties `matchdesk_dev` only (refuses any other database and production), runs `make up` and `make seed-demo` |
| `make web` | **Exists** (B4): Vite dev server on http://127.0.0.1:5173 proxying `/api/v1` to the API on 8101; installs `web/node_modules` on first use |
| `make web-check` | **Exists** (B4): web type check, ESLint, Vitest and production build (`web/dist`) |
| `make web-e2e` | **Exists** (B4; own stack since B6): Playwright E2E-01 and checks with axe-core, headless in the installed Google Chrome (no browser download). Creates `matchdesk_e2e` with its own API (8102), worker and web server (5174), seeds a tagged tenant there, drops it afterwards and fails if any `matchdesk_dev` row count changed; needs PostgreSQL and Mailpit, not `make up`. Screenshots for docs/UI.md: `cd web && SHOTS=after npx playwright test -c playwright.shots.config.ts` |
| `make test` | Unit and integration suites. **Exists**: drops and re-migrates `matchdesk_test` (migrations 0001 to 0016), runs as `matchdesk_app`; the B2 tests use Mailpit and MinIO (they skip, and say so, when either is not running) |
| `make check` | **Exists** (added in B1): ruff, format check, mypy, import contracts, top-level import rule (`backend/scripts/check_imports.py`), float lint over the whole package (`backend/scripts/check_no_float.py`) |
| `scripts/check_migrations` | Single head, ORM parity, manifest, lock rules. Proposed; head and parity are covered by `backend/tests/integration/test_migrations.py` |
| `scripts/load_fixtures` | Two synthetic tenants and golden fixtures |
| `scripts/eval_extraction` | Score an extraction provider on the fixture set |
| `make deploy TAG=<hash>` | Deploy a pinned image |
| `make restore SNAPSHOT=<id> TARGET=<env>` and `make verify-restore` | Restore and verify |
| `scripts/check_links` | Markdown links, anchors and web routes |
