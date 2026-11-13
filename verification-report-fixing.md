# Verification, findings and fixes — MatchDesk AP three-way match

Number labels follow [Decision.md section 0](Decision.md#0-how-numbers-are-labelled). Thresholds quoted from other documents keep the label they have there.

This file separates what has been checked in the documents from what can only be checked in the application. Build milestone B1 (section 9) added the foundation and the deterministic match core on 2026-11-11; the tests that ran are listed there with their commands and results. **Every application check not listed in section 9 is `Not run`.** A planned control or test is not evidence that anything works.

## 1. Status summary

| Area | Status |
|---|---|
| Ten planning documents written | Done by the author on 2026-11-10 |
| Author self-check of the documents | Done, and repeated after fix rounds 1 and 2; results in section 2 |
| Independent review, round 1 | 25 findings recorded in section 6 (2 blocker, 14 major, 9 minor). Fixes made by the author on 2026-11-10 |
| Independent review, round 2 (retest) | Reviewer's verdicts on F-001 to F-025: 17 closed, 8 open by design, none still open. Two new findings, F-026 (major) and F-027 (minor), fixed by the author on 2026-11-10 and closed by the reviewer in the final retest the same day. This was the second and last fix round |
| Go-to-market plan (Decision.md section 12), added after the review at owner request | Reviewed separately on 2026-11-10: findings F-028 to F-032 (2 major, 3 minor), fixed by the author the same day. Reviewer's retest: four closed; F-030 closed with a part open. That residue was edited afterwards by the author; the edit was checked by the lead, not re-reviewed |
| Application build | B1 (foundation and match core) implemented on 2026-11-11 on branch `feat/b1-foundation`, authorised by the owner before the Phase 0 gate (section 9); B2 sign-in and local services (section 10); B3 workflows through the API on the local stack, 2026-11-12, branch `feat/b3-workflows` (section 13). Not deployed |
| Application tests | B1 tests ran and passed on 2026-11-11 (section 9); B2 (section 10); B3 suite of 212 passed on 2026-11-12 (section 13); every other test `Not run` (section 3) |
| C1 corrections from an external review | Made on 2026-11-11, lead-checked, not independently reviewed (section 11) |
| Customer evidence | None. No customer has been interviewed |

## 2. Checks performed on the documents (author self-check)

These are checks of the repository's documents, performed by the author who wrote them. They are not an independent review.

| # | Check | Method | Result after fix round 2 |
|---|---|---|---|
| D-1 | Exactly ten root-level files with the required names | Directory listing | Pass |
| D-2 | Arithmetic in Decision.md sections 5.1 to 9 | Recomputed with a short script outside the repository from the inputs shown, using the same recurrence as the reviewer's script with the first subscription in months 6, 7 and 8: gross profit, payback, break-even with and without founder, both ramp tables, troughs, the downside case, the tier mix, prospects with churn, and every binomial figure in section 9 | Pass. Ramp tables compute on unrounded account counts; the note under the table says so |
| D-3 | Estimate totals in execution-plan.md section 5 | Summed the task ranges with a script | Pass at the time: 60 tasks, 431–686 hours; build 322–508; with release 338–534; smaller cut 142–225. Re-run by the author on 2026-11-10 after the go-to-market additions and fixes F-028 to F-032: 62 tasks, 455–726 hours (Phase 0 97–156); build, release and smaller-cut figures unchanged. See the dated note below |
| D-4 | Internal Markdown links and heading anchors | Script that resolves every relative link and anchor against the files | Pass: no broken link or anchor |
| D-5 | Every must-have MH-01 to MH-16 appears in PRD, App-flow inventory, execution-plan and the matrix in section 4 | Script | Pass |
| D-6 | Every user action in App-flow has an endpoint in TRD section 12 | Manual: the author listed each action verb under "Actions" and "States" for S-01 to S-19 and looked for a row in TRD section 12. First run (before review) missed eight actions the reviewer found (F-019). Second run after the fixes also found and added: decide a possible credit, "Stay signed in", tolerance preview, server-side draft save | Pass on the second run. This is a manual check and can miss things again |
| D-7 | Every table named in TRD, App-flow or execution-plan exists in schema.md | Script for back-ticked names plus manual read | Pass |
| D-8 | Every task has ID, link, owner, estimate, deliverable, acceptance check and subtasks | Script for subtasks; manual read for the rest | Pass |
| D-9 | All 22 risks present with IDs R-01 to R-22, a responsible task that exists, and a test that is an ID | Script | Pass |
| D-10 | Test IDs cited anywhere exist in execution-plan.md section 7 | Script | Pass: 95 test IDs defined |
| D-11 | Competitor and platform claims checked at a primary source or labelled unverified | Pages opened on 2026-11-10; see Decision.md section 13 (numbered 12 when this check was made) | Five vendor pricing pages, Intuit Canada pricing, Stripe Canada pricing, four Intuit-hosted pages on purchase-order receiving (two forum threads from 2020, one staff forum reply from 2023, one Intuit Australia post). Intuit developer documentation and one help article could not be read and are labelled unverified |
| D-12 | No real customer data, credentials or tokens | Manual read | Pass. Example companies are now named "Fictional Distributor A" and "Fictional Supplier T" |
| D-13 | Diagrams are Mermaid, fences balanced, no semicolons inside diagrams | Script | Pass. Rendering on GitHub has not been observed by the author |
| D-14 | Permission table in schema.md section 4.1 agrees with the role column of TRD section 12 and the App-flow inventory | Manual, row by row, after F-010 | Pass on the author's reading; the reviewer's retest decides |

Not checked by the author: rendering of Mermaid diagrams on GitHub; ASVS citations against the standard's own pages (the numbers used are the reviewer's); the fresh-reader test.

### Note dated 2026-11-10: go-to-market plan added after the independent review

At the owner's request the author added [Decision.md section 12, "Go-to-market plan"](Decision.md#12-go-to-market-plan) after the independent review and its retests were complete. It was then reviewed separately (`_coordination/review/matchdesk-ap-gtm.md`): findings F-028 to F-032 in section 6, fixed by the author and retested by the reviewer the same day (verdicts in section 6). The results in the table above and every verdict in section 6 were given on the repository as it stood before this addition and are unchanged.

What changed with it:

- Decision.md: new section 12; "Sources and assumptions" renumbered from 12 to 13; open founder decision 8 added to section 11. No existing figure was changed.
- execution-plan.md: discovery calls became their own task, T-0.2.5 (8–12 hours), taken out of T-0.2.2 (20–30 before, 12–18 now) and added to the critical path; T-0.1.1, T-0.2.1, T-0.2.2 and T-0.2.4 acceptance checks extended; one external dependency added (anti-spam confirmation). D-3 was passed on 60 tasks; with T-0.2.5 the count became 61 with the same hours. The F-030 fix then added T-0.2.6 (24–40 hours): 62 tasks, 455–726 hours, Phase 0 97–156.
- This file: the range of validation activities in section 3 now ends at T-0.2.6, the section reference in D-11 was updated, and D-3 shows both counts.
- Fix round for F-028 to F-032: Decision.md sections 12.3, 12.4, 12.5, 12.8 and 12.9 rewritten, paragraphs added to sections 7.5 and 9, decisions 1 and 8 of section 11 extended, sources SRC-13 and SRC-14 added; AGENTS.md source row now points to section 13. No figure in sections 1 to 10 was changed.

Author self-check of the addition, not an independent review: the arithmetic of section 12 was recomputed with a script outside the repository (100 × 3 = 300 prospects a month, 15 replies, 6 calls, 1.2 paid back-tests, 1.2 paying accounts a month as in section 7.5; 1,800 ÷ 1.2 = 1,500; the day-30, day-60 and day-90 table; the three binomial figures of 12.9; after the fixes also 33.8%, 12.2%, 69.2% and 33.7% in 12.8, the emailable-share table of 12.4, the solo-founder calendar of section 7.5, and the developer-cost table added there after the retest); the link and anchor script (D-4), the task-ID check and the task-total script (D-3) were re-run after the fixes and pass. Not verified by anyone: the author's reading of Canadian anti-spam law (statute and regulations read through a summarising fetch, SRC-13 and SRC-14; not legal advice; no lawyer consulted), and every rate in the plan, all of which are assumptions.

## 3. Application checks planned for future implementation

Definitions, fixtures and expected outcomes are in [execution-plan.md section 7](execution-plan.md#7-test-catalogue).

| Group | IDs | Status |
|---|---|---|
| Unit and property | UT-01 to UT-31 (thirty-one tests), PT-01 | B1: 29 of UT-01 to UT-31 and PT-01 ran and passed, some in part (section 9). UT-11 and UT-14 `Not run` |
| Integration | IT-01 to IT-29, with IT-07b and IT-16b (thirty-one tests) | B1: IT-02, IT-03, IT-05, IT-06, IT-07, IT-24 passed; IT-01, IT-08, IT-16, IT-16b, IT-17, IT-29 passed in part (section 9). Others `Not run` |
| Build checks | CI-01, CI-02, CI-03, CI-04 | B1: CI-01 and CI-04 passed locally (no CI pipeline yet). CI-02, CI-03 `Not run` |
| End-to-end | E2E-01 to E2E-08 | Not run |
| Accessibility and navigation | A11Y-01 to A11Y-06, NAV-01 | Not run |
| Operations | OPS-01 to OPS-06 | B1: OPS-04 passed with the local services, not Compose (section 9). Others `Not run` |
| Governance | GOV-01, GOV-02 | Not run |
| Network | NET-01 | Not run |
| Human review (extraction evaluation) | HR-01 | Not run |
| Load | LOAD-01, LOAD-02, LOAD-03 | Not run |
| Pilot measurements | M-1a to M-12 in PRD section 13 | Not run |
| Validation activities | T-0.1.1 to T-0.2.6 | Not started |

## 4. Traceability matrix

Each must-have traced through screen or API, design decision, schema or permission, task and planned test. Screens are in [App-flow.md](App-flow.md), APIs in [TRD.md section 12](TRD.md#12-api-contracts), design decisions in [design.md section 2](design.md#2-design-decisions) and TRD section 9, tables and permissions in [schema.md](schema.md), tasks and tests in [execution-plan.md](execution-plan.md). Every test is `Not run`.

| Must-have | Screen / API | Design decision | Schema / permission | Task | Planned test |
|---|---|---|---|---|---|
| MH-01 Workspace and roles | S-01, S-02, S-16, S-18, S-19; `/auth/*`, `/invitations`, `/memberships/{id}`, `/support-grants`, `/operator/tenants/{id}/support-session` | AD-02, AD-09 | `tenants`, `users`, `memberships`, `sessions`, `login_tokens`, `support_grants`; row-level security; operator policies; permission table 4.1 | T-2.2.1, T-2.2.3, T-5.1.5 | IT-01, IT-02, IT-03, IT-13, IT-18, IT-29, E2E-06 |
| MH-02 Read from QuickBooks, with open-PO history | S-03, S-04; `/qbo/connection`, `/qbo/sync-runs`, `/purchase-orders` | AD-07, AD-13 | `qbo_connections`, `sync_runs.mode`, `vendors`, `items`, `purchase_orders`, `po_lines`, `qbo_bills`, `qbo_bill_lines.po_line_id`; connect is controller-only, sync is controller or clerk | T-1.1.1, T-3.1.1, T-3.1.2, T-3.1.3 | IT-04, IT-11, NET-01, UT-14, E2E-01 |
| MH-03 Independent receiving evidence | S-05, S-12; `/receiving/imports*`, `/receiving/receipts/{id}/confirm`, `/receiving/attestation` | AD-05, DD-06 | `receiving_imports.evidence_class`, coverage dates, `source_type` incl. `qbo_item_receipt_export` (class A only); `receipts.receiver_marks_present`; `receipt_lines.counts`, `added_after_exception`; `approvals` (`late_receipt`); attestation is controller-only | T-3.2.1, T-3.2.2, T-4.2.3 | IT-07b, IT-28, IT-30, UT-13, UT-30, UT-32, E2E-01, A11Y-02 |
| MH-04 Batch intake | S-06; `/intake/batches*` | DD-08 | `upload_batches`, `documents` (seven stored states mapped to six shown, `state_version`), `idempotency_keys` | T-3.3.1, T-3.1.3, T-2.2.5 | IT-07, IT-05, IT-06, IT-19, A11Y-03, LOAD-01 |
| MH-05 Verified extraction | S-07; `/invoices/{id}/extraction`, `/invoices/{id}/confirm-extraction` | AD-06, DD-05 | `extraction_runs`, `invoices.verification_status`, `review_draft`, `invoice_lines.field_sources` | T-1.1.3, T-3.3.2, T-3.3.3 | UT-08, HR-01, E2E-05, IT-14 |
| MH-06 Three-way match, partial deliveries, history | S-09, S-10, S-15; `/match-runs`, `/tolerances`, `/tolerances/preview` | DD-01, DD-07, AD-10, AD-13 | `match_runs`, `line_matches` (`qty_invoiced_prior_qbo`, `line_kind`), `tolerance_rules` with two exclusion constraints, `ruleset_versions`; tolerance edit is controller-only | T-1.1.2, T-4.1.2, T-4.1.6, T-4.2.2, T-4.2.5 | UT-01, UT-02, UT-04, UT-09, UT-10, UT-12, UT-13, UT-15, UT-24, UT-25, UT-26, UT-27, UT-29, PT-01, CI-02, LOAD-02 |
| MH-07 Absent receipt is an exception and can be a finding | S-03, S-08 coverage strip, S-09, S-13 section 3; `/exceptions`, `/exceptions/{id}/resolutions`, `/onboarding/no-receiving-declaration` | DD-02, DD-13, AD-05 | Checks on `line_matches` and `exceptions`; `exceptions.sub_reason`, `qualifying`; no receipt-tolerance column; "confirm not received" is controller-only; bulk waiver refused | T-4.1.3, T-4.2.1, T-5.1.1 | UT-03, UT-16, UT-17, UT-23, UT-31, IT-22, IT-24, E2E-02 |
| MH-08 Duplicates | S-06, S-09; `/intake/batches/{id}/files`, `/exceptions/{id}/resolutions` | DD-03 | Partial unique on invoice file hash; `invoices.doc_number_norm`, `file_order_key`; `qbo_bills.doc_number_norm`; `exceptions.related_invoice_id` | T-4.1.4, T-3.3.1 | UT-05, UT-22, IT-07, PT-01 |
| MH-09 Credit notes, vendor credits, returns | S-09, S-10; `/invoices`, `/exceptions/{id}/credit-decision` | DD-01 | `invoices.doc_type`, `references_invoice_id`; `qbo_bills.txn_type`; `line_matches.qty_invoiced_cum_net`; `exceptions.possibly_credited_bill_id`; `resolved_by_credit`; negative `receipt_lines` | T-4.1.5 | UT-06, UT-18, UT-19, UT-20, UT-21, UT-28 |
| MH-10 Alias and unit map | S-11, S-12; `/aliases`, `/aliases/review-acknowledgement`, `/approvals/{id}/decision` | DD-12, DD-05, AD-08 | `item_aliases` (conversion, status, validity; check that conversion ≠ 1 needs approver); approval is controller-only | T-4.1.1, T-4.2.4, T-4.1.6 | UT-07, IT-15, IT-21 |
| MH-11 Exception queue and correction | S-08, S-09, S-12; `/exceptions*`, `/approvals` | DD-01, DD-09, DD-10, DD-14 | `exceptions` (version, fingerprint), `exception_events`, `approvals`; `tenants.waiver_limit`, `waiver_period_cap`; reopen is controller-only | T-4.2.1, T-4.2.2, T-4.2.3 | E2E-03, E2E-04, IT-13, IT-14, IT-23, IT-27, A11Y-01, A11Y-05, LOAD-03 |
| MH-12 Back-test report | S-13; `/reports/backtest*` | DD-04, DD-09 | `backtest_reports` (versions, frozen totals trigger, coverage by class, `qualifying_amount`), `report_findings`; approve is controller-only | T-5.1.1, T-5.1.2 | E2E-01, E2E-07, E2E-08, UT-11, UT-20, A11Y-06 |
| MH-13 Audit trail | S-17; `/audit-events`, `/audit-events/export` | TRD 8.6 | `audit_events` insert-only grant; `exception_events` | T-2.2.4, T-5.1.5 | IT-13, IT-16, IT-24 |
| MH-14 Live intake (P1) | S-06 email panel; `/hooks/inbound-email`, `/intake/email-settings`, `/intake/held-messages/{id}/release`, `/intake/held-messages/{id}/discard` | TRD 13.2 | `inbound_messages`, `intake_senders`, `tenants.intake_address_local` | T-3.3.4, T-3.1.2 | IT-12, IT-04 |
| MH-15 Weekly summary (P1) | S-14; `/reports/weekly` | DD-07 | Reads `exceptions`, `line_matches`, `invoices` | T-5.1.4 | IT-25 |
| MH-16 Usage, pilot record, refund | S-18, S-13 section 7, S-03; `/usage`, `/pilot-engagement`, `/operator/tenants/{id}/usage`, `/operator/tenants/{id}/pilot-engagements`, `/operator/pilot-engagements/{id}` | TRD 12 | `usage_events` (unique per invoice, `unit_month`), `pilot_engagements` (`governing_report_id`, `refund_threshold`, `refund_due`), `finding_outcomes` (controller-confirmed, credit recovered); operator policies | T-5.1.3, T-0.2.1, T-0.2.3, T-0.2.6, T-7.2.2 | IT-17, IT-26, IT-29, IT-13, UT-33 |

**Paid-pilot promise followed end to end.** "We check last month and show you what was overbilled; if we find nothing you get your CAD 500 back." Requirement MH-12, MH-16 and the criterion in Decision.md section 5.1 → inputs including open-PO history (MH-02, MH-06) → screens S-03, S-06, S-05, S-08, S-09, S-13 section 7 → controller-only report approval; operator records the governing version (schema 4.1) → `pilot_engagements.governing_report_id`, `refund_qualifying_amount`, `refund_due`; `backtest_reports.qualifying_amount`; `report_findings` → recovery: a later report version does not change the recorded result → delivery before the application exists: by hand, T-0.1.4 method, M0.2 → tasks T-0.2.1, T-0.2.3, T-5.1.1 to T-5.1.3, T-7.2.1, T-7.2.2 → tests IT-17 (refund result for five cases), UT-12 and UT-13 (month boundary), E2E-01, E2E-07, E2E-08.

**Failure scenario followed end to end.** "An invoice line with no real receipt." Requirement MH-07, MH-03 → S-03 declaration and attestation, S-05 evidence class and coverage, S-08 coverage strip, S-09 sub-reason, S-13 section 3 → declaration, attestation, late-evidence approval and "confirm not received" are controller-only → check constraints on `line_matches` and `exceptions`; `receipt_lines.counts`; `exceptions.sub_reason`, `qualifying` → recovery by importing receiving evidence (re-match), with controller approval if it arrives after the exception → tasks T-3.2.1, T-3.2.2, T-4.1.3, T-4.2.3, T-5.1.1 → tests UT-03, UT-16, UT-17, UT-23, UT-30, IT-22, IT-24, IT-28, E2E-02 → commercial consequence in Decision.md section 9, clause 4.

## 5. Production risk register

This is the only home of the 22 production risks. Other documents cite the ID. Each row gives the impact on this product's buyer and data, prevention, detection signal, test with expected outcome, and the responsible task. All tests are `Not run`.

| ID | Risk | Impact here | Prevention | Detection signal | Test and expected outcome | Task |
|---|---|---|---|---|---|---|
| R-01 | Out-of-order or duplicate events overwrite a newer job state | A late "running" event flips an extracted invoice back to processing, or a stale match run replaces newer results computed after a receiving import; the controller sees exceptions that were already cleared, or a report built on old receipts | `state_version` compare-and-set on documents, sync runs, imports and match runs; match runs keyed by input fingerprint; current results swapped in one transaction | Log count of stale transitions; any line with zero or two current results | IT-05: stale and repeated events update zero rows and state is unchanged. IT-15: re-match supersedes, never overwrites. PT-01: results do not depend on arrival order. B1 2026-11-11: IT-05 and PT-01 passed; supersede-not-overwrite passed in `test_golden_flow_supersede_and_credit`; IT-15 `Not run` (section 9) | T-3.1.3, T-4.1.6 |
| R-02 | A caller timeout prevents reconciliation with a valid later completion | The clerk's upload times out in the browser though the server stored it, and they upload again; or an extraction returns after its lease expired and the invoice stays "processing" for ever, so it never reaches the back-test | Idempotency keys on every mutating request; pages rebuild from server state; late results accepted if the row is still running for the same input, otherwise discarded; sweep of rows stuck in `running` | Rows in `running` past twice the lease; idempotency replays counted | IT-06: late completion and second attempt leave exactly one result and no `running` row. IT-07: re-upload creates no new documents. B1 2026-11-11: IT-06 and IT-07 passed (section 9) | T-3.1.3 |
| R-03 | New utilities duplicate behaviour already owned by shared code | Two rounding helpers or two invoice-number normalisers give different answers; a duplicate is detected at upload but missed in the report, or a price variance differs by a cent between screen and export | `core.money` and the normalisers in `matching` are the only implementations; a utilities index in AGENTS.md; lint rule rejecting float arithmetic and ad-hoc rounding outside `core` | Review checklist item; lint failures | UT-09: half-up rounding through the single helper. CI-04: a second rounding function or float arithmetic outside `core.money` fails lint. B1 2026-11-11: UT-09 and CI-04 passed locally (section 9) | T-2.1.4 |
| R-04 | Applications import private code across architectural boundaries | The rule engine starts reading the database or the API layer directly, so match results stop being reproducible from inputs and the golden fixtures no longer prove what production does | Import-linter contracts: `matching` imports only `core`; domain modules never import `api` or `worker`; access through public interfaces | CI contract failure | CI-01: a commit importing `api` from `matching` fails CI. B1 2026-11-11: CI-01 passed locally; no CI pipeline yet (section 9) | T-2.1.1 |
| R-05 | Tenant enforcement is scattered or bypassed through APIs, workers, caches or files | One distributor sees another's supplier prices or findings. In a regional market they may share suppliers or compete; this ends the pilot and the product | Row-level security on every tenant table; tenant set in one helper; job wrapper refuses payloads without tenant; file keys built from context; no server cache; composite foreign keys; CI check for tables without a policy | Any `tenant_mismatch` log line; 404 rate per user | IT-01, IT-02, IT-03: every cross-tenant read, write, job and file request returns nothing. B1 2026-11-11: IT-02 and IT-03 passed; IT-01 passed for the B1 endpoints only (section 9) | T-2.2.1 |
| R-06 | Workers copy configuration and utility modules, causing behavioural drift | The worker applies a 0.5% price tolerance default while the API preview shows another; the controller's tolerance screen predicts results the match run does not produce | One image, one `core` settings object, one rule module used by both entry points; no copied files | Settings hash logged at start by both processes and compared | CI-02: API and worker log the same settings hash; the tolerance preview on S-15 equals the following match run on the fixture set | T-2.1.4 |
| R-07 | Worker logging imports web-only modules and crashes during startup | After a deploy the worker fails to start; uploads queue silently and the back-test stalls while the web app looks healthy | Logging lives in `core` with no web framework dependency; worker readiness check; queue-age alert | Worker `/readyz` failing; oldest queued job age | IT-16b: worker starts and processes a job with web-only packages unimportable. B1 2026-11-11: IT-16b passed (import check with web packages blocked; section 9) | T-2.1.4 |
| R-08 | ORM declarations omit indexes or constraints present in migrations | The check that a matched line must have receipt lines, or the unique current-result index, exists in one place only; a later autogenerated migration drops it and an absent receipt can be stored as a pass | CI parity check between migrations and models; manifest for policies, triggers, partial and GIN indexes compared with the catalogue | CI failure | IT-08: clean database from migrations shows no diff; a model-only index makes the check fail. B1 2026-11-11: IT-08 first half passed (no diff, single head); the model-only-index failure case `Not run` (section 9) | T-2.2.2 |
| R-09 | Interrupted migrations or backfills cannot resume safely | A backfill of normalised invoice numbers stops half-way; duplicates among unprocessed rows are missed in a pilot report | Backfills are batched jobs with a progress row, idempotent per batch; concurrent-index migrations drop invalid leftovers first | Backfill progress row not finished; invalid index in catalogue | IT-09: killed after three batches, re-run completes and each row changes once | T-2.2.2 |
| R-10 | Merged branches introduce conflicting migration order | Two developers each add a migration; production applies them in an order nobody tested and a deploy fails during a pilot week | Single linear history; CI fails on more than one head | CI failure | CI-03: two branches each adding a migration; the second to merge fails CI until rebased | T-2.2.2 |
| R-11 | Index creation locks busy production tables during deployment | Adding an index to `line_matches` or `exceptions` blocks the clerk's queue and a running match for minutes | Concurrent index builds, one per migration; `NOT VALID` then validate; `lock_timeout` 5 s | Deploy log showing lock timeout; request latency during deploy | OPS-06: in staging, hold a long transaction on `exceptions`, run the migration: it fails fast on lock timeout, and succeeds on retry without blocking reads | T-2.2.2 |
| R-12 | Correlation IDs disappear across jobs and retries, or sensitive data leaks into logs | When a controller disputes a figure, the upload cannot be traced to its extraction and match run; or supplier unit prices appear in log files that are kept and copied with fewer protections than the database | Correlation ID stored in job payloads and on `documents`, `extraction_runs`, `match_runs`, `audit_events`; scrubbing filter; allow-list of loggable fields | Share of log lines without correlation ID; scrub-test failure | IT-16: one correlation ID across request, job, retry and match run; no fixture price, document text or token in captured logs. B1 2026-11-11: IT-16 passed in part: no fixture price, document number or token in logs; correlation ID carried from request to job (section 9) | T-2.1.4 |
| R-13 | Upload keys collide or fail to isolate tenant, source and purpose | Two suppliers both send `invoice.pdf`; one overwrites the other and the evidence shown beside a finding is the wrong document; or a receiving file lands where an invoice is expected | Keys are `t/{tenant}/{purpose}/{source}/{yyyy}/{mm}/{record}/{sha256}`; user file names never used in paths; `blob_key` unique with a check that it starts with the row's tenant | Unique-violation count; hash mismatch on read | IT-03: key outside tenant prefix refused. IT-07: identical names with different content are stored separately; identical content is one document. B1 2026-11-11: IT-03 key refusal passed (section 9). B2 2026-11-11: keys now follow the full format with the document ID as record and the sniffed extension; upload, download and cross-tenant refusal against MinIO passed (`test_b2_files.py`, section 10) | T-2.2.5 |
| R-14 | Temporary uploads survive retention expiry or failed cleanup | Raw supplier emails, abandoned receiving previews and exported reports with cost prices stay on disk after the periods promised in the pilot agreement | `expires_at` on temporary documents; daily sweeper with counts; orphan-blob cleanup; alert on failure | Count of rows past `expires_at`; sweeper failure alert | IT-10: expired files and the orphan blob are removed; a simulated failure alerts and is retried | T-2.2.5 |
| R-15 | Missing persistent volumes cause data loss after service recreation | Recreating containers during a deploy wipes the database or every invoice PDF of a pilot account; the back-test cannot be evidenced | Named volumes for database, blobs and proxy data in the Compose file; start-up refuses if a volume is missing or empty when the database expects files; nightly offsite backup | Start-up check failure; backup-age alert | OPS-03: recreate all containers, data intact. OPS-01: timed restore on a different machine from offsite backups and the offsite copy of the keys | T-7.1.1, T-7.1.2 |
| R-16 | Generated file links use internal hosts or `localhost` behind a public proxy | The controller's sign-in email, the weekly summary link or the QuickBooks redirect points at an internal address; they cannot sign in or connect, and Intuit rejects the redirect | One `PUBLIC_BASE_URL` for all generated links; start-up validation; files are streamed through the API, no storage links | Start-up failure; link check in staging | OPS-05: sign-in email, export and authorise URL all use the public HTTPS host; bad setting stops start-up | T-7.1.1 |
| R-17 | Local dependencies and workers lack a reliable single startup command and health checks | A developer tests the API without a worker and concludes uploads work; or the founder cannot bring the stack back alone after a reboot during a pilot | One proposed start command that waits for readiness of every service; readiness covers database, volume and migrations | Start command exit code | OPS-04: clean checkout to healthy stack within 3 minutes; with the database stopped the command fails with a clear message. B1 2026-11-11: OPS-04 passed for `make up` with services run directly; Compose stays proposed (section 9) | T-2.1.2 |
| R-18 | Browser Back, refresh or deep links lose the user's result or task state | A clerk 40 exceptions into a filtered queue presses Back and lands on an unfiltered first page; a controller's emailed link to a finding opens the home page | Filters, sort, cursor and selection in the URL; long work as server jobs; every route deep-linkable; sign-in restores the requested URL | Front-end error reports; support questions | E2E-03: filter, page and selection survive Back, Forward, refresh and a shared URL | T-4.2.1, T-6.1.4 |
| R-19 | Bulk processing skips files, hides partial failures or duplicates successful work on retry | A month of 240 invoices is uploaded, 2 fail silently, and the back-test reports "nothing found" on the invoices that mattered; or a retry re-extracts 238 good files and bills them twice | Per-file state rows; totals that must sum to the file count; "retry failed" selects failed only; hash-unique documents; usage unique per document; bulk resolve returns per-item results | Batch total ≠ sum of states (metric M-11); duplicate usage events | IT-07: 228 + 9 + 2 + 1 = 240; retry touches only the 2 failed; re-upload adds nothing. B1 2026-11-11: IT-07 passed (section 9) | T-3.3.1 |
| R-20 | Unclear labels, icons, stale routes or broken links misdirect users | "Received" is read as warehouse receipt when it is QuickBooks' billed quantity; "Approve" is confused with "Matched"; an old link in a weekly email leads nowhere | Fixed vocabulary (design section 9); icon always with word; one route table; link and route check in CI; redirects for removed routes | Link-check failures; clerk questions logged in pilot | NAV-01: all navigation, email and document links resolve. A11Y-04 greyscale review: statuses distinguishable | T-6.1.4 |
| R-21 | Unrequested features consume effort without a requirement or pilot need | Time goes to bill posting, a Sage connector or dashboards while the pilot question (will they supply receiving data and pay) stays unanswered and cash runs down as in Decision.md section 7.5 | Every pull request cites an MH, R or operational need; deferred list in PRD section 9 with the evidence that would admit each item; pilot requests logged and triaged at Gate B | Pull requests without a reference; hours on items outside the plan | GOV-01: every merged pull request maps to an ID; the request log has accept or decline with reason | T-2.1.3, T-7.2.4 |
| R-22 | Misnamed, duplicate or stale branches obscure the active work or endanger unmerged changes | With one to three developers, a fix to the match rules sits on an old branch and never reaches the pilot; or a cleanup deletes unmerged rule changes | Protected default branch; branch names `<type>/<task-id>-<slug>`; merged branches deleted automatically; weekly stale-branch report; never delete an unmerged branch without its owner | Stale-branch report | GOV-02: no branch older than 14 days without an open pull request; no unmerged branch deleted | T-2.1.3, T-7.2.4 |

All 22 risks apply to the planned design; none is marked not applicable. R-16 would widen if files moved to object storage with pre-signed links (TRD AD-04); R-05's cache clause would become active if a server-side cache were added.

## 6. Findings register

Review findings use IDs `F-001`, `F-002`, …. The independent reviewer's findings are recorded below (evidence and impact are shortened; the full text is in the lead's coordination records). The author made every fix on 2026-11-10 and is the owner of each. For F-001 to F-025 the last column carries the independent reviewer's round 2 verdict as written in the reviewer's note file, not the author's opinion: "Closed" or "Open by design". For F-026 and F-027, found in round 2 and fixed afterwards, it carries the reviewer's final-retest verdict from the same note file: both closed. No further fix round is planned, so anything not closed is listed again under [Outstanding items](#8-outstanding-items).

| ID | Severity | File (as reported) | Evidence | Impact | Owner | Fix made | Files changed | Retest result |
|---|---|---|---|---|---|---|---|---|
| F-001 | Blocker | Decision §5; PRD MH-02, MH-06; TRD §8.5; App-flow S-03, S-05; tests | Inputs were one calendar month; receiving rows outside the period were rejected; QuickBooks bills never entered cumulative invoiced quantity | Month-boundary false pass (invoice billed in September and re-billed in October passes) and false exceptions | Author | Back-tests now take open-PO history: purchase orders read by reference whatever their date, every linked bill and credit, receiving of any date, earlier invoices from QuickBooks bill lines or uploaded PDFs; new check `history_incomplete`; no date-window rejection of receiving rows; AD-13. Fixtures UT-12 (prior-month invoice, over-invoicing caught), UT-13 (prior-month receipt, pass), UT-14, UT-15. Open: whether QuickBooks exposes bill lines linked to PO lines (T-1.1.1); if not, earlier PDFs are required and check 6 flags the gap | Decision.md, PRD.md, TRD.md, App-flow.md, schema.md, execution-plan.md, AGENTS.md, CLAUDE.md | Open by design. Remaining: T-1.1.1 must show QuickBooks exposes bill lines linked to PO lines, or at least a billed quantity; if neither exists a replacement control must be specified. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-002 | Blocker | schema `exceptions` check; TRD §8.5; PRD MH-07, MH-11; Decision §5, §9 | `receipt_absent` could only be waived or corrected and could never be a finding | Total non-delivery could not be reported or counted; a back-test finding only non-deliveries ended in a refund | Author | Receiving coverage defined (class A log declared complete from PO date to 14 days after invoice date). `receipt_absent` now has sub-reasons `not_received` (finding candidate), `supplier_slip_only`, `no_evidence` (unverified); the controller may confirm any as "not received". Schema check rewritten: never a pass, may be a finding; `qualifying` flag; refund criterion counts it and prints the unverified total beside the result. Fixtures UT-16, UT-17; IT-24 | Decision.md, PRD.md, TRD.md, schema.md, App-flow.md, design.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-003 | Major | Decision §5; PRD MH-16; schema; T-5.1.3; trace | Refund depended on the controller's own confirmation and on any value above CAD 0; no governing version; no test | Buyer controls the refund; a cent defeats it; result can flip; the promise the pilot is sold on was untested | Author | Chat term quoted; Decision §5.1 proposes an objective criterion: qualifying discrepancies evidenced by the rule table and removable only by evidence, not by waiver or non-confirmation; threshold CAD 500; governing version fixed 10 business days after the first clean draft; later versions do not change the result; residual risk stated. Schema: `pilot_engagements.governing_report_id`, `refund_threshold`, `refund_due`; `backtest_reports.qualifying_amount`. Test IT-17 with five fixtures. Open: the founder must accept or change the proposal (Decision §11) | Decision.md, PRD.md, schema.md, App-flow.md, design.md, execution-plan.md, TRD.md | Open by design. Remaining: Founder acceptance of the refund proposal (Decision §11 item 2). Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-004 | Major | Decision §7.5; execution-plan gates, §5, M7.2, T-0.2.3 | Ramp assumed subscriptions in month 3 while the build takes months; no statement of how Phase 0 back-tests are delivered | Cash need understated; unclear what a Phase 0 buyer receives | Author | Ramp rebuilt on the build timeline: first subscription in month 7 (base), 6 and 8 as sensitivities; troughs −27,826 without founder (month 14) and −188,841 with founder (month 43); the three cases reproduce the reviewer's figures (−25,126 / −27,826 / −30,526 and −180,141 / −188,841 / −197,541). Phase 0 back-tests are delivered by hand in 12–20 hours within 15 business days, live checking owed at release; stated in Decision §5, M0.2, T-0.2.1, T-0.2.3. Month-1 double count of outreach stated | Decision.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-005 | Major | Decision §9; PRD M-1, M-2; M0.1, M0.2 | Revised threshold equals the expected value; cohort cost above budget; M-1 used the unaccepted window; M-2 needed the application | A working funnel is stopped about 40% of the time; ambiguous window | Author | Decision §9 now reports the false-stop and false-go probabilities (40.5% unconditional, 37.6% given 10 demos, 64.5% with qualification, 26.4% false go at half rate, 65.1% for the 5-of-8 gate), states the CAD 550 budget overrun and the 340-prospect alternative, and says plainly that no threshold is reliable at these counts. Rule in force named: the chat's 30 days; proposal day 60. M-1 split into M-1a and M-1b; M-2 redefined as a Phase 0 census measure. Open: the founder chooses the rule and accepts the risk | Decision.md, PRD.md, execution-plan.md | Open by design. Remaining: Founder's choice of rule and acceptance of about 40% false-stop risk. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-006 | Major | Decision §7.5, §8 | 6,750 prospects ignored churn | With-founder break-even probably unreachable by cold outreach in the launch market, not said in §1 or §4 | Author | Decision §8 adds 9,900 prospects (27 accounts, 33 cohorts) and 11,400 (positive monthly cash); §1 and §4 state the consequence; T-0.1.1's acceptance check compares the list with 500, 9,900 and 11,400. Open: the universe count itself, which only T-0.1.1 can supply | Decision.md, execution-plan.md | Open by design. Remaining: T-0.1.1's count. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-007 | Major | Decision §3; PRD MH-03; App-flow S-05; TRD §13.1; schema | A supplier packing slip counted as independent; the clerk could supply the receipt that clears an exception | Hole in the central independence rule | Author | Three evidence classes defined; class C (supplier document only) never counts and leaves the line `receipt_absent` with sub-reason `supplier_slip_only`; class B needs recorded receiver marks and signer; controller attestation; evidence added after an exception needs controller approval; coverage reported by class; threat-model row; schema fields. Tests UT-30, IT-28 | Decision.md, PRD.md, TRD.md, schema.md, App-flow.md, design.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-008 | Major | PRD MH-09; TRD §8.5; UT-06 | QuickBooks vendor credits only shown; no rule for price-only credits, post-period credits, returns | False finding on something already credited | Author | Credit table added to TRD §8.5 and MH-09: QuickBooks credit tied by number or line is netted and labelled; tied only by amount is flagged `possibly_credited` and reported as open; price-only credits net the variance; credits netted up to the data cut-off; returns as negative receipts; checks not run on credit lines. Tests UT-18 to UT-21, UT-28. Open: what a QuickBooks vendor credit can be tied to (T-1.1.1) | PRD.md, TRD.md, schema.md, App-flow.md, execution-plan.md | Open by design. Remaining: T-1.1.1: what a QuickBooks vendor credit can be tied to. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-009 | Major | TRD §8.5; schema §7; PT-01 | Tie-break by upload time in one file; duplicates possibly double counted | Result depended on arrival order; inflated findings | Author | One order everywhere: document date, normalised number, file content hash. A `duplicate` document's lines are `not_evaluated` and excluded from cumulative quantities; a `possible_duplicate` is reported as open until decided. Test UT-22; PT-01 includes a duplicate pair | TRD.md, schema.md, PRD.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-010 | Major | schema §4; TRD §8.2, §12; App-flow S-04, S-18 | Operator path undefined against row-level security; four disagreements between permission table, API and screens | No single oracle for the permission test | Author | Operator path defined: operator-only policies on three tables without bypassing row-level security; read-only `support_reader` session under a grant. Permission table rewritten as the single oracle; TRD role rule and rows, `/usage`, S-04 and the inventory aligned. Tests IT-13, IT-29; check D-14 | schema.md, TRD.md, App-flow.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-011 | Major | TRD §7, §8.3, §10; OPS-01 | Backup passphrase and keys only on the VPS; restore drill on the same machine; staging shares the host | Targets for loss of the VPS unverifiable; backups could be unreadable | Author | Offsite custody of every production secret stated; OPS-01 now restores on a different machine from offsite material only; staging uses only staging keys; shared host and the absence of a secrets manager (ASVS 5.0.0 13.3.1, 13.3.2 as cited by the reviewer) recorded as accepted pilot gaps with a revisit trigger | TRD.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-012 | Major | TRD §8.1, AD-09, §13.2; App-flow S-01, S-02; schema | Email-only sign-in with no level chosen, 15-minute link, token in URL, scanner prefetch, no test | Weak authentication for a system holding accounting tokens | Author | ASVS 5.0.0 named, Level 1 targeted for the pilot with a table of accepted Level 2 gaps (multi-factor for tenant users, session list). Link: 10 minutes, 256-bit, fragment transport, consumed only on POST, bound to the requesting browser, rate limits; operator TOTP. Test IT-18; threat row points to it. Open: multi-factor for tenant users is a stated gap, to be revisited before a sixth account or any write access | TRD.md, App-flow.md, schema.md, execution-plan.md | Open by design. Remaining: No MFA for tenant users is an accepted pilot gap with a trigger. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-013 | Major | TRD §8.7, §13.2; IT-07 | No test of hostile files; no archive limits, headers or malware scan | Control without planned evidence; supplier PDFs rendered in the app origin | Author | File limits (size, pages, pixels, archive entries, expansion, entities), worker limits, response headers including content security policy, sandboxed downloads, PDF.js without scripting. Tests IT-19 and IT-20. Malware scanning recorded as an accepted gap for the back-test and required before email intake | TRD.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-014 | Major | design §4, §10, §11; A11Y-04 | Work screens became read-only below 1024 px, so 200% zoom lost function; files contradicted each other | WCAG 2.2 SC 1.4.4 failure for the main user | Author | Work screens now stack and keep every function down to 640 px (1280 px at 200%); design §4, §10, §11 and A11Y-04 agree. **Still open, stated as a known AA gap:** between 320 and 639 px eight work screens lose editing (SC 1.4.10) | design.md, execution-plan.md | Open by design. Remaining: SC 1.4.10 on the eight work screens, to be closed before general release. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-015 | Major | TRD §8.1; App-flow §4.3, S-08, S-09; design §11 | No timeout warning; focus destinations and page titles unspecified | SC 2.2.1, 2.4.2, 2.4.3 | Author | Idle warning with unlimited extension; absolute lifetime 20 hours; focus destination stated for route change, dialog close, "Resolve and next" and Back; page-title rule; design rows for 2.2.1 and 2.4.2; A11Y-01 extended; A11Y-05 added | TRD.md, App-flow.md, design.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-016 | Major | verification §3, §4; execution-plan §7 | Several P0 criteria and false-pass mechanisms had no test ID; some risk tests were prose | Traceability overstated | Author | 42 tests added (UT-12 to UT-30, IT-17 to IT-29, CI-01 to CI-04, E2E-08, A11Y-05, A11Y-06, OPS-06, GOV-01, GOV-02); matrix, section 3 and every risk row now cite IDs | execution-plan.md, verification-report-fixing.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-017 | Minor | App-flow S-04; TRD §4, §13.2; T-1.1.1 | "Reads only" may not match what Intuit's scope grants | UI statement could misdescribe the grant | Author | T-1.1.1 now records scopes and consent wording; S-04 copy is conditional on that result; the token is treated as write-capable in the threat model. **Open:** needs T-1.1.1; Intuit developer documentation could not be read | App-flow.md, TRD.md, schema.md, execution-plan.md | Open by design. Remaining: T-1.1.1. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-018 | Minor | design §5, §8, §11; App-flow S-06 | Focus ring 2.57:1 on the dark banner; original value on hover only; 5 s versus 15 s; export accessibility unstated; no 1.3.5 or 3.2.6 rows | Several AA details | Author | White focus ring on dark surfaces; "History" button instead of hover; one cadence (screen 5 s, announcements at most every 15 s); export accessibility requirement and A11Y-06; rows for 1.3.5, 1.4.13, 3.2.6 | design.md, App-flow.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-019 | Minor | TRD §12; self-check D-6 | Eight App-flow actions had no endpoint | D-6 "Pass" unsupported | Author | Endpoints added for all eight, plus four more found on the re-run; D-6 method and its limits stated | TRD.md, verification-report-fixing.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-020 | Minor | schema §3, §4.3; TRD §6 | Seven schema defects (a) to (g) | Non-deterministic tolerance; undefined charge status; and others | Author | (a) two exclusion constraints; (b) `charge_ok` status and `line_kind`; (c) invoice-only file uniqueness; (d) state names aligned and seven-to-six mapping; (e) `nullif` in the policy; (f) `unit_month` defined; (g) several invoices per file | schema.md, TRD.md, PRD.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-021 | Minor | Decision; PRD | Eight research-record items missing | Lost competition risk, qualification rule, week-4 gate and others | Author | All eight added to Decision §2, §4, §5 with labels; items not used in calculations listed in §12 with reasons | Decision.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-022 | Minor | CLAUDE.md; App-flow S-03; design DD-06; Decision §3 | A weak claim stated as fact downstream and titled a "finding" | Certainty rose as the claim moved | Author | Heading changed to "assumption"; the two newer Intuit pages the reviewer named were opened and added as SRC-11 and SRC-12; user-facing copy and DD-06 now state MatchDesk's rule, not a fact about QuickBooks; CLAUDE.md hedged. Remains an assumption until T-1.1.1 | Decision.md, PRD.md, App-flow.md, design.md, CLAUDE.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-023 | Minor | Decision §5, §6, §7.1; opening lines of five files; design label | What CAD 500 covers unstated; founder figure label; a fourth label; blanket labels | Fresh-reader gap; labelling drift | Author | CAD 500 covers the 30-day pilot, subscription from day 31; pilot-month variable cost shown; founder figure labelled a chat-stated assumption; fourth label removed; tier limits count credit notes; packing-slip extraction cost named as a missing input. Key proposed numbers now also carry an inline label where they are introduced. **For the lead:** the blanket opening sentence is kept as the fallback for minor design parameters | Decision.md, PRD.md, design.md, TRD.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-024 | Minor | PRD MH-11; TRD §13.2; App-flow §4.3; schema | No cumulative waiver cap; sender allow-list forgeable; prices in session storage; response bodies stored | Business-logic and data-handling gaps | Author | Rolling 30-day waiver cap with weekly list and test IT-27; sender authentication result required; nothing in browser storage, server-side drafts, `no-store`; idempotency table stores a reference, not a body | PRD.md, TRD.md, App-flow.md, schema.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-025 | Minor | CLAUDE.md, PRD §10, TRD §6.2, Decision §3; execution-plan §1 | Four different "highest" failures; no signatory; "Phase 0 is the first milestone" | Fresh reader cannot rank or tell who signs | Author | One ranked table in Decision §1, cited by CLAUDE.md and PRD §10; controller named as signatory and payer (proposal) in Decision §2 and PRD §6; wording fixed to M0.1 | Decision.md, CLAUDE.md, PRD.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md` |
| F-026 | Major (regression from the F-001 and F-002 fixes) | TRD §8.5 checks 6 and 7; E2E-02; IT-17 case (c); PRD MH-16; App-flow S-03 | The rule table made `history_incomplete` and `receipt_absent` stop evaluation, so price and ordered-quantity checks never ran on those lines, while three tests, one PRD example and the "two-way only" report expected them to | For an account with no receiving evidence the back-test would report no price or over-order discrepancy; refund criterion and M-3 would undercount | Author | TRD §8.5: the two conditions are recorded on the line and block `matched` but do not stop; after `receipt_absent` check 8 is skipped and checks 9 and 10 run; after `history_incomplete` checks 7 to 10 run; duplicates are document-level. One line result, several exception rows; `reported_amount` per exception so a line's amounts never exceed the line amount (finding amounts capped, unverified reports the remainder). Schema: `exceptions.reported_amount`, `line_matches.checks_run`. PRD MH-07 example; App-flow S-03 and S-09; E2E-02 and IT-17 (c) reworded; new fixture UT-31 with four cases; CLAUDE.md | TRD.md, schema.md, PRD.md, App-flow.md, execution-plan.md, CLAUDE.md, verification-report-fixing.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md`, section "Round 2 final retest" |
| F-027 | Minor (six residues from fix round 1) | (a) schema §3.1, §4.3; (b) App-flow S-02, TRD §12; (c) schema `sync_runs`; (d) design §10, A11Y-04; (e) TRD §8.1, design §11; (f) IT-12 | (a) operator policy lacked insert; (b) invitation token in a path; (c) sync idempotency index null in the new mode; (d) S-04 and S-18 unclassified; (e) absolute lifetime exactly 20 hours; (f) no sender-authentication failure in IT-12 | Self-contradictions beside statements that a requirement is met | Author | (a) policy now select, insert, update. (b) route `/invite` with the token in the fragment and `POST /invitations/accept` with it in the body, in both files. (c) `scope_fingerprint` and a partial unique index on it. (d) all nineteen screens classified: eleven fully supported, eight not. (e) absolute lifetime 24 hours in TRD, App-flow, design and IT-18. (f) IT-12 has a listed sender failing SPF and DKIM, expected held. Also the reviewer's wording point: Decision §9 now relates the CAD 2,000–2,550 cost of a wrong stop to the CAD 7,400 the ramp charges | schema.md, TRD.md, App-flow.md, design.md, execution-plan.md, Decision.md | Closed (all six items). Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md`, section "Round 2 final retest" |
| F-028 | Major | Decision §12.3, §12.4, §12.5; execution-plan §2, T-0.1.1, T-0.2.1, T-0.2.2 | The anti-spam paragraph named LinkedIn as a fallback although such messages are also covered; asked only about member-list addresses while the list used tool-found contacts; follow-up and closing emails lacked identification and unsubscribe; no suppression field; referral rule missing; confirmation could come from a peer | A founder could follow the fallback believing it lawful; the reachable list is smaller than the count by an unknown share | Author | Author read the Act and Regulations at Justice Laws (SRC-13, SRC-14; through a summarising fetch, stated as such; not legal advice). §12.4 now tabulates what is covered, the consent basis per channel (published role-relevant address, s. 10(9)(b); none for tool-found addresses; phone outside s. 6; address given on a call; first referral message), content and unsubscribe duties and the penalty. LinkedIn messages removed from the sequence. List rows marked emailable or phone only with the publication recorded; emailable count separate; funnel restated by emailable share (100%, 50%, 25%; list cost exceeds the ramp's 1,800 below 58%). All three emails carry a footer; log has a "do not contact" date. Send gated on a lawyer's confirmation or the founder's written acceptance (decision 8). **Open:** the legal point itself and the emailable share | Decision.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-gtm.md`, section "Retest" |
| F-029 | Major | Decision §12.4, §12.8, §12.9, §9, §11; T-0.2.2, T-0.2.5, M0.2 | Schedule, hours and tasks used 300 a month while the stop rule was framed on 500; the 33.8% pass chance on 300 was not shown; signal 3 mistimed against clause 3 | The plan as scheduled ends in "stop" about two times in three with a working funnel, and the reader was not told | Author | One volume everywhere: 300 a month at 100 emailable prospects a week; "or the cohort the founder chose" removed from T-0.2.2; hours 12–18 and 8–12 match it. §12.8 states the chance of passing at day 30 (cold: close to nil), day 60 (33.8%; 12.2% at half rate) and day 86 if extended (69.2%; 33.7%), and what follows: choice (a) stop or (b) one more cohort, costing CAD 2,700 or 8,700 on the trough. §9 clause 1 carries a note; decision 1 extended; M0.2 exit criteria state it; signal 3 tied to choice (b). **Open:** the founder's choice | Decision.md, execution-plan.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-gtm.md`, section "Retest" |
| F-030 | Minor | Decision §12.8, §7.5; execution-plan M0.2 | No task owned delivery of a sold back-test; the build calendar ignored 34–54 hours a month of selling and delivery | A paid promise with a deadline had no owner or exit check; month 7 optimistic for a solo founder | Author | Task T-0.2.6 added (24–40 hours for the two sales Gate A requires, per-sale exit check); totals now 62 tasks, 455–726 hours, Phase 0 97–156. §7.5 and execution-plan §5 state that month 7 needs a developer other than the selling founder; solo founder: month 8 (low) or month 11 (high; −38,626 and −223,641) | Decision.md, execution-plan.md, verification-report-fixing.md | Closed, part open: the month-7 base case now depends on a developer other than the selling founder, whose cost (CAD 33,800-53,400 at the model rate) is not in the ramp; section 11 item 6 still says only month 7. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-gtm.md`, section "Retest". Residue edited afterwards by the author; that edit was checked by the lead, not re-reviewed |
| F-031 | Minor | Decision §12.5 | Messages asked only for last month's PDFs and claimed "about an hour" of clerk time | Understated what the buyer must supply, on the first cause of a false pass | Author | First touch lists four inputs including earlier invoices and credit notes on still-open purchase orders; follow-up names them and the one-line confirmation of who keeps the receiving log; the time claim is removed until T-0.1.4 measures it | Decision.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-gtm.md`, section "Retest" |
| F-032 | Minor | AGENTS.md; this file, D-3 | AGENTS.md sent sources to Decision section 12; D-3 said 60 tasks | An agent would add sources to the wrong section | Author | AGENTS.md says section 13; D-3 row shows the original result and the re-run (62 tasks) | AGENTS.md, verification-report-fixing.md | Closed. Independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-gtm.md`, section "Retest" |

F-028 to F-032 come from the separate review of the go-to-market plan (`_coordination/review/matchdesk-ap-gtm.md`, 2026-11-10). Their last column carries the reviewer's retest verdict from the "Retest" section of that note file. After the retest the author edited Decision.md section 7.5 (developer cost shown beside the base ramp as an excluded item) and section 11 item 6 (both readings) for the F-030 residue; that edit was checked by the lead, not re-reviewed.

No finding is disputed. One reviewer remark outside the numbered findings was also acted on: example company names were replaced with plainly invented ones.

### Author self-check log

Issues the author found and fixed while cross-checking the documents. These are not independent findings.

| ID | File | Issue found | Fix applied |
|---|---|---|---|
| SC-01 | TRD.md | App-flow.md described actions with no API: voiding a receiving import, withdrawing a pending resolution, declaring "no receiving records", email-intake settings and held messages | Added the five endpoints to TRD section 12 |
| SC-02 | schema.md | The migration rules referred to a `backfill_progress` row with no table defined | Added the table to section 3.6 |
| SC-03 | execution-plan.md | Tasks in Phases 4 to 7 had no subtasks | Added subtasks for every task |
| SC-04 | TRD.md | Sequence-diagram messages contained semicolons, which Mermaid can read as statement separators | Replaced with commas |
| SC-05 | Decision.md | The brief's secondary evidence said ProcurementExpress's USD 415 plan includes three-way matching; the vendor's pricing page read on 2026-11-10 does not use the term and lists "Scan & Match" only on its USD 2,550 plan | Decision.md section 3 states the page's content and moves the lowest verified three-way price to Precoro's USD 499 |
| SC-06 | TRD.md, App-flow.md | Fix round 1, D-6 re-run: four actions still had no endpoint (decide a possible credit, "Stay signed in", tolerance preview, server-side draft save) | Endpoints added |
| SC-07 | execution-plan.md, Decision.md | Fix round 1 added work, so ten task estimates and every figure derived from them were out of date | Estimates raised; totals, calendar and cost figures recomputed (431–686 hours; build with release 338–534) |
| SC-09 | several | Fix round 2 added one test (UT-31), so counts of tests quoted in this file were out of date | Counts updated to 95 |
| SC-08 | Decision.md | A sentence written in fix round 1 said the Reading B account cap never reaches 27 below 600 prospects a month; the correct figure is 337 | Corrected with its arithmetic |

## 7. Open items that documents cannot close

| Item | Needed from | Blocks |
|---|---|---|
| Do target distributors hold receiving records independent of the invoice? | T-0.1.2 | The product |
| Will a controller pay CAD 500 for a back-test? | T-0.2.2, T-0.2.3 | The product |
| QuickBooks Online API facts, limits and programme fee | T-1.1.1 | MH-02 design details; fixed cost |
| Number of distinct reachable prospects | T-0.1.1 | Funnel and stop rule |
| Founder decisions listed in Decision.md section 11 (stop rule and its false-stop risk, refund criterion, evidence definition, build size, signatory) | Founder | T-0.2.1, T-0.2.4 |
| Whether QuickBooks exposes bill lines linked to purchase-order lines, what vendor credits can be tied to, and which OAuth scopes exist | T-1.1.1 | Open-PO history from QuickBooks (F-001), credit netting (F-008), consent wording (F-017) |
| WCAG 2.2 SC 1.4.10 on eight work screens below 640 px | Design and build work after the pilot | Known AA gap (F-014) |
| Multi-factor sign-in for tenant users; secrets manager; malware scanning | Decisions before a sixth account, a cloud move, and email intake respectively | Accepted pilot gaps (F-011, F-012, F-013) |
| Tier mix, churn, support cost, refund rate | Paying accounts | Unit economics |
| VPS location and size | Founder | Data-residency wording; T-7.1.1 |
| Legal reading of privacy and breach-notification duties (original: "Counsel") | Answered by compliance/self-check.md sections 3 to 5, owner sign-off recorded 2026-11-11 (Decision.md section 11 decision 11) | Pilot agreement |
| Whether the outreach of Decision.md section 12.4 complies with anti-spam law; the share of prospects whose address is published | Anti-spam: answered by compliance/self-check.md section 1, owner sign-off recorded 2026-11-11 (original: "Counsel"); share: T-0.1.1 | T-0.2.2 first send; the funnel and list cost (F-028) |

## 8. Outstanding items

Findings the independent reviewer marked "open by design" in round 2, followed by two items left open by the go-to-market fixes. Each is honestly labelled in the documents; none can be closed by editing them. Source of the verdicts: independent reviewer, 2026-11-10, `_coordination/review/matchdesk-ap-round2.md`.

| Finding | What remains open | Evidence or decision needed | Who supplies it |
|---|---|---|---|
| F-001 Open-PO history | Whether earlier invoices can be taken from QuickBooks. If QuickBooks exposes neither bill lines linked to PO lines nor a billed quantity, check 6 loses its cross-check, nothing detects a missing earlier invoice, and the month-boundary false pass returns | The T-1.1.1 fact sheet; and, if neither field exists, a replacement control specified in TRD section 8.5 | T-1.1.1 (developer, QuickBooks sandbox) |
| F-003 Refund criterion | The criterion in Decision.md section 5.1 (qualifying discrepancies, CAD 500 threshold, governing version, accepted residual risk) is a proposal | Acceptance, change or rejection before the pilot agreement is written (T-0.2.1) | Founder decision (Decision.md section 11, item 2) |
| F-005 Stop rule | Which rule is adopted, and acceptance of a false-stop risk of about 40% and a CAD 550 budget overrun for a 500-prospect cohort | A recorded choice between the chat's 30-day rule and the day-60 proposal | Founder decision (Decision.md section 11, item 1) |
| F-006 Reachable market | Answered in part by C1: the launch market cannot hold the 9,900 distinct prospects the ramp needs for 27 accounts ((900 + 6,000) ÷ 256.18 contribution after churn-replacement acquisition; 24 with no acquisition spend), nor 11,400 for positive monthly cash with founder compensation; Statistics Canada counts 610 qualifying-size locations in the Vancouver CMA and 889 in BC (Decision.md section 8). What remains: the qualified count, and how the plan grows past it | The de-duplicated qualified count (T-0.1.1); owner decision 10 of Decision.md section 11 | T-0.1.1; founder |
| F-008 Credits from QuickBooks | What a QuickBooks vendor credit can be tied to (invoice number, PO line, or only vendor and amount), which decides how often a credit is netted automatically and how often it is only flagged | The T-1.1.1 fact sheet | T-1.1.1 |
| F-012 Sign-in strength | No multi-factor authentication for tenant users (ASVS 5.0.0 item 6.3.3 as cited by the reviewer); no user-visible session list | A decision to add it, due before a sixth paying account or any write access to QuickBooks | Accepted pilot gap; founder decision at the trigger |
| F-014 Reflow | Between 320 and 639 px of layout width, eight work screens lose their editing functions (WCAG 2.2 SC 1.4.10) | Design and build work to make those screens operable at 320 px, due before general release | Accepted pilot gap; developer after the pilot |
| F-017 QuickBooks permission | Whether Intuit offers a read-only scope and what its consent screen says; until known, the "reads only" statement is conditional and the token is treated as write-capable | The T-1.1.1 fact sheet (scopes and consent wording) | T-1.1.1 |
| F-028 Anti-spam law (closed by the reviewer; open by design) | Whether the consent bases in Decision.md section 12.4 hold, and how many prospects have a published, role-relevant address | Original: "A lawyer's confirmation or the founder's written acceptance of the risk". Answered by compliance/self-check.md section 1, owner sign-off recorded 2026-11-11 (Decision.md section 11 decision 11); residual risk medium. Still open: the emailable count | T-0.1.1 |
| F-029 Stop rule on 300 prospects (closed by the reviewer; founder choice remains) | Whether a miss at day 60 stops the plan or extends it to day 86 | A recorded choice between (a) and (b) of Decision.md section 12.8 before day 1 | Founder decision (Decision.md section 11, item 1) |

| F-030 Who builds, and the developer's cost | The reviewer's verdict was "closed, part open". The author then stated the developer cost beside the base ramp and both readings in Decision.md section 11 item 6; that edit was checked by the lead, not re-reviewed. Who builds is still undecided | The founder's choice of reading (a) or (b) | Founder decision (Decision.md section 11, item 6) |

The first eight rows are findings the reviewer marked "open by design". The reviewer closed F-028 and F-029 in the go-to-market retest; their rows record what, by the reviewer's own residue notes, only a lawyer or the founder can settle. For F-028 the legal part was settled in round C2 by compliance/self-check.md section 1 and the owner's decision of 2026-11-11; only the emailable count remains.

F-026 and F-027 were retested by the independent reviewer on 2026-11-10 and are closed. F-028 to F-032 were retested the same day: F-028, F-029, F-031 and F-032 closed; F-030 closed with a part open, since edited as described above. Nothing awaits retest.

## 9. Build milestone B1 (2026-11-11)

**Authorisation.** On 2026-11-11 the owner authorised implementation in this repository before the Phase 0 sales gate of [execution-plan.md section 1](execution-plan.md#1-sequence-and-gates) had passed, and asked for the smaller 142–225 hour cut of [execution-plan.md section 5](execution-plan.md#5-estimate-summary). The decision text in Decision.md is unchanged; the Phase 0 evidence it asks for still does not exist. B1 is the first part of that cut: foundation and deterministic match core. Nothing is deployed and no customer data was used; every fixture is synthetic.

### 9.1 Tasks implemented

| Task | What exists | Limits |
|---|---|---|
| T-2.1.1 | Package layout of TRD section 5 under `backend/src/matchdesk`; four import-linter contracts (`matching` imports `core` only; `core` standard library only; domain modules never import `api` or `worker`; `worker` never imports `api` or a web framework) | CI pipeline (T-2.1.3) not built; contracts run locally through `make check` |
| T-2.1.2 | `make up` / `make down`, `/healthz`, `/readyz` (database, migrations at head, blob volume writable) | Services run directly on this machine; the Compose stack of TRD section 7 stays proposed (no Docker here) |
| T-2.1.4 (in part) | `core`: settings object, JSON logging with an allow-list scrubber and correlation IDs, `core.money` (Decimal only, half-up once, floats refused), clock, errors; float lint `scripts/check_no_float.py` | Proxy-created correlation IDs: there is no proxy; the API creates or accepts `X-Correlation-Id` |
| T-2.2.1 | Migrations 0001 and 0002: 28 tables, 23 tenant-owned with `ENABLE` and `FORCE ROW LEVEL SECURITY` and one policy each, composite tenant foreign keys, role `matchdesk_app` (NOSUPERUSER NOBYPASSRLS), `tenancy.session()`, job queue and job wrapper refusing payloads without `tenant_id` | Subset of schema.md; differences in schema.md section 9.1 |
| T-2.2.4 (in part) | Audit writer used inside the match-run transaction; `audit_events` and `exception_events` insert-only by grant and trigger | History query not built |
| T-2.2.5 (in part) | `blobstore` key builder, tenant-checked put and get; streamed download with sandbox headers | Content sniffing, limits, sweeper not built |
| T-4.1.1 | Alias resolution with unit conversion; conversion ≠ 1 passes only when approved | Suggestion query (trigram) not built |
| T-4.1.2 | Cumulative quantity and price checks over open-PO history including QuickBooks bill lines; history-incomplete check; document order by date, normalised number, file hash; charge lines; property test | |
| T-4.1.3 | `receipt_absent` with three sub-reasons, coverage rule, class rules (A, B with marks, C never), no tolerance input; check constraints and trigger in the database | |
| T-4.1.4 | Number normalisation, exact and possible duplicates, QuickBooks-bill cross-check, content-hash tie-break, exclusion from cumulative quantities | |
| T-4.1.5 | Credit-note linking and netting, price-only credits, QuickBooks vendor credits without a document, possibly-credited flag, returns, `credit_unlinked` | Credit decision endpoint (M4.2) not built |
| T-4.1.6 (in part) | Match runs unique on input fingerprint; queued by API, executed by worker; results superseded and kept; exceptions reconciled by fingerprint (keep, reopen, auto-close) with events | Automatic triggers on alias, tolerance or import change not built; stale-report flag not built (no reports table) |
| T-3.3.1 (in part) | Batches, file intake idempotent on key, byte-identical files as `duplicate_file`, document leases, late completions, retry-failed | No HTTP upload endpoint; fake extractor only |

**Blocked or not started.** T-1.1.1 (QuickBooks sandbox fact sheet) is blocked: it needs an Intuit developer account and keys, which B1 must not create. QuickBooks sits behind `qbo.QboReader` with `FakeQboReader`; there is no write method. T-1.1.3 (extraction provider choice) is blocked for the same reason; `extraction.FakeExtractor` stands in. T-3.1.1, T-3.1.2 (QuickBooks connect and sync), T-3.2.1 (receiving import), T-3.3.2 (extraction beyond the arithmetic gates) and T-5.1.1 (report) are in the smaller cut but not in B1. T-2.2.3 (sign-in links, invitations, operator TOTP) is not built: B1 sessions are created only by the test fixtures. No frontend was built.

### 9.2 Commands and results

All commands run from the repository root on 2026-11-11, Python 3.12.16, PostgreSQL 16.15. The integration suite drops and re-creates the `public` schema of `matchdesk_test` and migrates it from scratch at the start of every run; every test query runs as `matchdesk_app`.

| Command | Result |
|---|---|
| `make check` (ruff check, ruff format --check, mypy strict, lint-imports, top-level import check, float lint over the whole package) | Pass after review round 1: ruff no findings; 74 files formatted; mypy no issues in 48 source files; 5 contracts kept, 0 broken; `check_imports.py` and float lint clean |
| `cd backend && .venv/bin/pytest -q tests/unit` | 60 passed, 0 failed (45 before review round 1, 58 before round 2) |
| `cd backend && .venv/bin/pytest -q tests/integration` | 56 passed, 0 failed (46 before review round 1, 53 before round 2; 23 are one parametrised zero-rows test per tenant-owned table) |
| `make test` (both suites, clean test database) | 116 passed, 0 failed (91 before review round 1, 111 before round 2) |
| `make up`, then `curl localhost:8101/readyz`, then `make down` | Ready in 3 s (2 s after review round 1, migrating to 0003); `{"status":"ready"}`; services stopped |
| `MATCHDESK_MIGRATION_DATABASE_URL=...localhost:5999... make up` | Exit 2 with "database not reachable (is PostgreSQL running? ...)" |

### 9.3 Test IDs that ran

Tests not listed here remain `Not run`.

| ID | Test function(s) | Result |
|---|---|---|
| UT-01 to UT-07, UT-10 | `tests/unit/test_matching.py::test_ut01…` to `test_ut07b…`, `test_ut10…` | Pass |
| UT-08 | `test_gates_and_permissions.py::test_ut08…` (gate function); routing to review shown by IT-07 | Pass, in part (only the arithmetic gates of T-3.3.2 exist) |
| UT-09 | `test_money.py::test_ut09…` | Pass |
| UT-12, UT-13, UT-15 | `test_matching.py::test_ut12…`, `test_ut13…`, `test_ut15…`; UT-12 also through the database in `test_match_runs.py::test_ut12_qbo_bill_history_through_database` | Pass |
| UT-16, UT-17 | `test_ut16…`, `test_ut16b…`, `test_ut17…`; clerk refusal in `test_gates_and_permissions.py::test_ut17…` | Pass (the refusal is the permission function; no resolution endpoint yet) |
| UT-18, UT-19, UT-21 to UT-31 | `test_ut18…` to `test_ut31…`, `test_ut22b…`, `test_ut22c…`, `test_ut30b…` | Pass |
| UT-20 | `test_ut20…` | Pass, in part: the late credit is netted; the report and its cut-off date are not built |
| PT-01 | `test_order_independence.py::test_pt01…` (Hypothesis, 60 generated sets × up to 24 orders; also equal fingerprints) | Pass |
| IT-01 | `test_tenancy.py::test_it01…` | Pass for the B1 endpoints (match runs, invoices, exceptions, document content): 404, no B data in bodies, no B row changed |
| IT-02 | `test_it02…` | Pass |
| IT-03 | `test_it03…` | Pass (blobstore refusal, path traversal, database check on `blob_key`) |
| IT-05, IT-06, IT-07 | `test_intake.py::test_it05…`, `test_it06…`, `test_it07…` | Pass (synthetic files and the fake extractor) |
| IT-08 | `test_migrations.py::test_single_head`, `test_orm_parity` | Pass, in part: the model-only-index failure case and the manifest compare are not built (T-2.2.2) |
| IT-16 | `test_match_runs.py::test_golden_flow_supersede_and_credit` | Pass, in part: no fixture price, document number or token in captured logs; one correlation ID on request and job. Retries and the proxy are not covered |
| IT-16b | `test_worker_boundary.py::test_it16b…` | Pass, in part: the worker module and its handlers import with `fastapi`, `starlette` and `uvicorn` blocked; processing a job in that state was not run |
| IT-17 | `test_refund.py::test_it17a…`, `b`, `c`, `e` | Pass, in part: the calculation over engine results with threshold 500.00; fixture amounts differ from the catalogue. (d), governing-report immutability, `Not run` (no report or pilot tables) |
| IT-24 | `test_guards.py::test_it24…` (four tests) and `test_receipt_absent_cannot_link_to_a_matched_result` | Pass |
| IT-29 | `test_tenancy.py::test_it29…` | Pass, in part: the operator session sees zero rows in every tenant table. Operator endpoints and support grants are not built |
| CI-01 | `test_ci01_boundaries.py::test_ci01…` | Pass locally |
| CI-04 | `test_money.py::test_ci04…` | Pass locally |
| OPS-04 | `make up` (section 9.2) | Pass for the local services: ready in 3 s, under the 3-minute target. "Stopped database" was simulated with an unreachable port, because stopping the shared PostgreSQL service is not allowed on this machine |

Further B1 tests without a catalogue ID: forced RLS and exactly one policy on every tenant table, no unprotected table outside the global allow-list, inserts without tenant context refused, composite foreign key refuses a cross-tenant reference, the application role is not superuser and cannot bypass RLS, line-match status cannot be updated, tolerance rules have no receipt column and cannot overlap, a viewer cannot start a match run, unapproved conversions do not pass, voided, uncommitted and unapproved late receipt lines do not count.

### 9.4 Decisions and document changes made during B1

| Change | Files |
|---|---|
| Check 8 and 9 tie: when both fail with equal amounts, `qty_over_received` carries the reported amount and `qty_over_ordered` reports 0.00. UT-12's fixture fails both checks (200 invoiced against 100 received and 100 ordered); its expected outcome now says so | TRD.md section 8.5; execution-plan.md UT-12 |
| Job queue: a PostgreSQL table `job_queue` behind `tenancy.jobs` instead of Procrastinate, so that enqueue shares the business transaction without a second connection pool. Same properties as the TRD row; Procrastinate is not rejected, only not adopted in B1 | TRD.md section 4 |
| Module imports: `exceptions` reads the models of `qbo`, `receiving` and `intake` to assemble match inputs; `intake` calls the `extraction` interface for document processing | TRD.md section 5 |
| Schema subset and differences (receipt-line counting computed by the rule engine from evidence fields, `late_approved`, `extraction_runs.in_use`, `po_lines.charge_kind`, `qbo_bills.references_invoice_number`, `exceptions.label`, `job_queue`, tables not yet built, local owner role) | schema.md section 9.1 |
| State lines that said no code exists | AGENTS.md, CLAUDE.md |

A defect found and fixed during B1: two check constraints on `exceptions` passed when `sub_reason` or `resolution_code` was null, because a null comparison makes a `CHECK` true. Both now use `coalesce`; IT-24 caught it.

### 9.5 Review round 1 fixes (2026-11-11)

Source: independent code review `_coordination/review/matchdesk-ap-b1-round1.md` (1 blocker, 5 major, 5 minor). The reviewer's scripts `matchdesk-ap-b1-core_adversarial.py`, `-db_adversarial.py`, `-db_aba_pass.py` and `-db_aba_receipt.py` were run from `backend` with `.venv/bin/python -I` before the fixes (AC-02, AC-03, AC-08 with tolerance 10, AC-09, AC-10, DB-01, DB-01b, DB-01c, DB-02 broken) and after them (every case holds; AC-05 now gives `alias_unconfirmed` and `uom_unresolved`). Each defect has a permanent regression test in `backend/tests/unit/test_review_round1.py` or `backend/tests/integration/test_review_round1_db.py`. These fixes are recorded by the author and have not been re-reviewed.

| Finding | Fix | Regression test |
|---|---|---|
| B1-001 (blocker) | A finished run is reused only if its inputs are identical **and** it is still the current result for every line in its scope; pending runs stay idempotent. Migration 0003 replaces the unique fingerprint constraint with a partial unique index on pending runs. A return to an earlier input state now creates a new run that supersedes the newer result | `test_b1_001_receipts_removed_after_a_match_re_evaluate`, `test_b1_001_voided_vendor_credit_re_evaluates` (the stored result equals `evaluate()` on current inputs) |
| B1-002 | A QuickBooks bill line is skipped only when an uploaded invoice line on the same PO line was counted; an earlier unresolved invoice line with no bill standing in makes later lines on that PO `history_incomplete` | `test_b1_002_unresolved_earlier_line_does_not_hide_its_qbo_bill` (both billed quantities), `test_b1_002_unresolved_earlier_line_without_bill_blocks_as_history_incomplete` |
| B1-003 | Duplicate credit notes are value class none, not qualifying, not netted; a possible duplicate credit is not netted until cleared | `test_b1_003_credit_note_uploaded_twice_is_not_a_finding_and_nets_once`, `test_b1_003_possible_duplicate_credit_is_not_netted_until_decided` |
| B1-004 | Counting receipts that net to zero or less are `receipt_absent` under any tolerance (superseded after round 2 by B1-012, section 9.6: never a pass, and a qualifying `returned_no_credit` finding) | `test_b1_004_net_zero_receipts_never_pass_and_keep_the_finding` (tolerance 0 and 10) |
| B1-005 | Check C1 is cumulative per PO and charge kind against the PO charge amount plus the allowance once per PO | `test_b1_005_freight_is_cumulative_against_the_po_amount` |
| B1-006 | Test invoices are loaded even without a vendor; a vendor-less document stops at check 1 as `extraction_unverified` | `test_b1_006_vendor_less_test_invoice_is_an_exception` |
| B1-007 | Fake extractor parses numbers as `Decimal`; raw output stored as strings; float lint covers the whole package; the engine refuses floats in any input | `test_b1_007_fake_extractor_reads_decimals_not_floats`, `test_floats_refused_at_the_engine_boundary` |
| B1-008 | A line with no unit is taken in PO units only for a non-converting alias; a factor-1 alias with different units needs approval, in the engine and in the database check (migration 0003) | `test_b1_008_units_assumed_only_when_the_alias_does_not_convert`, `test_b1_008_database_refuses_unapproved_unit_changing_alias` |
| B1-009 | `scripts/check_imports.py` enforces the top-level import rule with an explicit allow-list of model imports, run by `make check`; `tenancy` and `core` exports used instead of submodules; a fifth contract keeps `exceptions` away from `identity`, `blobstore` and `reporting`. TRD section 5 states the rule as enforced | `test_b1_009_top_level_import_rule_is_enforced` |
| B1-010 | API authenticates before parsing the body (401 problem+json); 422 is problem+json without echoing input; expired idempotency keys are not replayed; a concurrent request with the same key replays the stored result | `test_b1_010_auth_before_validation_and_problem_json`, `test_b1_010_expired_key_not_replayed_and_concurrent_key_replays` |
| B1-011 | Match runs of a tenant execute under a per-tenant advisory transaction lock and read inputs after taking it | `test_b1_011_out_of_order_runs_leave_current_inputs_result` (out-of-order execution; true parallel execution was not tested) |
| Review note on the 8/9 tie | The tie is now an explicit priority, not alphabetical order | `test_tie_rule_is_explicit_priority` |

Still open after round 1 (both closed by the fixes in section 9.6, which are not yet retested): there is no automatic trigger that starts a match run when a receipt is removed or a credit voided (T-4.1.6 triggers are not built). Until a run is requested, the stored result stays the earlier one; a run requested afterwards re-evaluates. AC-08 also changes meaning: a delivery fully returned with no credit is now `receipt_absent` (unverified unless covered), no longer a `qty_over_received` finding labelled "returned, credit not yet received". The label still applies when some quantity is kept.

Documents changed in round 1: TRD.md sections 5, 6.3 and 8.5 (checks 1, 2, 5, 7, the history paragraph, C1); schema.md 3.5 (`match_runs`, `item_aliases`) and 9.1; this section.

### 9.6 Review round 2 (retest) and fixes after it (2026-11-11)

Reviewer's verdicts, copied unchanged from `_coordination/review/matchdesk-ap-b1-verdicts.json` (round 2, commit `1947b9f`):

| Finding | Severity | Verdict | Open part |
|---|---|---|---|
| B1-001 | blocker | Closed, part open | No stale marker on read: after inputs change and before the next run, GET /api/v1/invoices/{id} shows the old run's line as matched while evaluate() on current inputs gives receipt_absent (N-01b). Remaining part is still a blocker. |
| B1-002 | major | Closed |  |
| B1-003 | major | Closed |  |
| B1-004 | major | Closed, part open | Never a pass now, but the fix removes the dollar finding for a full return; see B1-012. |
| B1-005 | major | Closed |  |
| B1-006 | major | Closed |  |
| B1-007 | minor | Closed |  |
| B1-008 | minor | Closed |  |
| B1-009 | minor | Closed |  |
| B1-010 | minor | Closed |  |
| B1-011 | minor | Closed |  |

New finding in round 2:

| Finding | Severity | Summary |
|---|---|---|
| B1-012 | major (regression) | Fully returned delivery with no complete class A log becomes receipt_absent no_evidence unverified; the 42.00 qualifying qty_over_received (returned_no_credit) finding of round 1 is lost and the refund qualifying total drops to 0.00 (N-04). |

Observation: Approved alias conversion_factor can be changed in place by the application role and approved_by survives; when alias edits are built, a factor or unit change must clear approval or version the alias (MH-10).

The edits below were **fixed after retest**: the author recorded them and they have not been re-reviewed. The reviewer's script `matchdesk-ap-b1-round2_new.py` was run before them (N-01b and N-04 when not covered broken) and after them (N-01a to N-01d, N-03a, N-03b and all four N-04 cases hold; N-02 now shows that an in-place factor edit clears the approval). The four round-1 scripts still hold.

| Item | Fix (fixed after retest) | Regression test |
|---|---|---|
| B1-001, open part | Stale on read: every read recomputes the input fingerprint of the result's run scope. `GET /invoices/{id}` returns a changed line as `status: stale` with `result_status` and `stale: true`, and sets `stale` on its exceptions and on the body. `GET /exceptions/{id}` and `GET /match-runs/{id}` carry `stale` too. No background job. B1 has no list endpoint or report yet; TRD 6.3 requires both to use the same comparison | `test_review_round2_db.py::test_b1_001_voided_receipt_import_reads_stale_before_any_new_run` (void, read before any run, re-run, un-void, read again), `test_b1_001_document_added_on_po_in_scope_reads_stale` |
| B1-012 | When counting receipt lines net to zero or less, check 8 runs with no tolerance. The result is a qualifying `qty_over_received` finding with sub-reason `returned_no_credit` (42.00 in the fixture), covered or not. It is never `matched`; a credit note for the returned quantity removes the finding | `test_review_round1.py::test_b1_004_net_zero_receipts_never_pass_and_keep_the_finding` (now asserts the 42.00 finding and a qualifying total of 42.00), `test_b1_012_full_return_is_a_qualifying_finding_covered_or_not` |
| Alias observation (MH-10) | Migration 0004: a database trigger clears approval and sets a converting alias to `pending_approval` on any change of factor, units or item. `exceptions.rematch_alias` re-matches every invoice whose current result used the alias; until then those results read as stale | `test_review_round2_db.py::test_alias_conversion_change_resets_approval_and_rematches` |

Still open: no alias edit endpoint calls `rematch_alias` (alias screens are not built). No input change starts a run automatically; the reader sees `stale` until a run is requested.

Documents changed in round 2: TRD.md sections 6.3, 8.5 (check 7) and 12 (invoices row); schema.md 9.1; AGENTS.md utilities index; this section.

### 9.7 Review round 3 (final retest) and the open item fixed after it (2026-11-11)

Reviewer's verdicts, copied unchanged from `_coordination/review/matchdesk-ap-b1-verdicts.json` (round 3, commit `6e7bf6f`). Reviewer reproduced: `make test` 116 passed (unit 60, integration 56); `make check` clean; 5 contracts kept; import rule and float lint clean.

| Finding | Severity | Verdict |
|---|---|---|
| B1-001 | blocker | Closed |
| B1-002 | major | Closed |
| B1-003 | major | Closed |
| B1-004 | major | Closed |
| B1-005 | major | Closed |
| B1-006 | major | Closed |
| B1-007 | minor | Closed |
| B1-008 | minor | Closed |
| B1-009 | minor | Closed |
| B1-010 | minor | Closed |
| B1-011 | minor | Closed |
| B1-012 | major | Closed |

Counts: closed 12, closed part open 0, still open 0, new 0. Observations, unchanged:

- Changing an approved converting alias's supplier_item_code keeps its approval (vendor column not tested); handle when alias editing is built (T-4.1.1, MH-10).
- rematch_alias exists but nothing calls it yet; the stale marker covers the gap until a run is requested.
- B1 has only detail endpoints; stale-on-read for list and report endpoints cannot be tested until they exist.
- A full return later fully credited ends as line status exception with only a resolved exception; no dollar effect.

The edit below was **fixed after round-3 retest, lead-checked**: the lead named the item; it has not been re-reviewed by the reviewer.

| Item | Fix | Regression test |
|---|---|---|
| Alias key observation (MH-10) | Migration 0005 adds `item_aliases.supplier_description` (the dictionary column used as the alias's description key) and extends the trigger `item_aliases_reset_approval`: a change of supplier (`vendor_id`), `supplier_item_code`, `supplier_item_code_norm` or `supplier_description` clears `approved_by`, increments `version` and returns a converting alias to `pending_approval`, also when the same statement sets `approved_by`. Updates of other columns keep the approval | `test_review_round2_db.py::test_round3_alias_key_change_resets_approval` (5 cases: vendor, code with norm, norm only, description changed, description cleared; each also checks the invoice line no longer reads `matched`), `test_round3_alias_unrelated_update_keeps_approval`. With the trigger conditions of 0004 only, all 5 cases fail; with 0005 they pass |

Commands and results after the fix (from `matchdesk-ap/`): `make test` (drops and re-migrates `matchdesk_test`, 0001 to 0005): 122 passed, 1 warning (httpx deprecation); `pytest -q tests/unit` 60 passed, `pytest -q tests/integration` 62 passed; `make check` exit 0 (ruff, format, mypy, 5 contracts kept, import rule, float lint).

Limit, stated as a gap: list and report endpoints do not exist yet, so stale-on-read is proven only on the detail endpoints `GET /invoices/{id}`, `GET /match-runs/{id}` and `GET /exceptions/{id}`. TRD section 12 requires list and report endpoints to use the same comparison when they are built. The other observations stay open: nothing calls `rematch_alias` yet, and a fully credited full return ends as `exception` with only a resolved exception.

Documents changed: schema.md 9.1 (migration 0005 row); this section.

## 10. Build milestone B2: sign-in and local services (2026-11-11)

Authorised by the owner on 2026-11-11 (build what needs no external account), still before the Phase 0 gate. Branch `feat/b2-local-auth`, from the B1 head after the round-3 open item (section 9.7). Synthetic data only; no real provider, account or key.

### 10.1 What was built

| Task | Built | Not built (reason) |
|---|---|---|
| T-2.2.3 (a) sign-in links | `POST /auth/login-links` (same 202 answer for every address; mail sent after the response), `POST /auth/sessions` (token in the body, binding cookie required, single use, 10 minutes), operator TOTP | A web page for `/login/verify` (no frontend in B2) |
| T-2.2.3 (b) cookie and anti-forgery | `__Host-md_session` (HttpOnly, Secure, SameSite=Lax, Path=/), `X-CSRF-Token` on every mutating request, origin check on public POSTs; idle 60 minutes, absolute 24 hours, `POST /auth/session/extend`, `DELETE /auth/session`, `GET /me`, `PUT /me/active-tenant`. The B1 bearer header is removed; the fake remains only as `issue_session` in test fixtures | Proxy access-log rule (no proxy locally) |
| T-2.2.3 (c) invitations | `POST/GET /invitations`, `DELETE /invitations/{id}`, `POST /invitations/accept` (7 days, single use, token in fragment and body) | |
| T-2.2.3 (d) permission table as data | `tenancy.permissions` (schema.md 4.1 rows; `can()`), used by every B1 and B2 endpoint | IT-13 over every endpoint of TRD 12 (most endpoints do not exist yet) |
| T-2.2.3 (e) last-controller guard | Database trigger; `PATCH /memberships/{id}` (role or deactivation; not one's own; deactivation deletes that user's sessions in the tenant); `GET /users` | |
| Operator path | TOTP at sign-in; `identity.enroll_operator` | Support grants, `support_reader`, operator endpoints (T-5.1.5) |
| Mail (TRD 3) | `core.mail.SmtpMailer` to Mailpit at 127.0.0.1:1025 without authentication; provider later through `MATCHDESK_SMTP_*` only | Inbound mail (MH-14) |
| T-2.2.5 (a) blobstore over S3 | `blobstore.S3Store` to MinIO (`matchdesk-dev`, region `us-east-1`), `LocalStore` kept; key `t/{tenant}/{purpose}/{source}/{yyyy}/{mm}/{record}/{sha256}.{ext}`; private bucket, no public or presigned URL; `POST /intake/batches`, `POST /intake/batches/{id}/files` (content sniffing for PDF, PNG, JPEG; 20 MB); download only through `/documents/{id}/content`; readiness checks the bucket | Page, pixel, XLSX and CSV limits; retention sweeper (IT-10); malware scanning (accepted gap, TRD 8.7) |

Out of scope and deferred: OIDC or any outside identity provider (not in the design: AD-09 uses emailed links); real mail provider; real object storage provider; deployment.

Local secrets: `backend/.env` (gitignored, mode 600) holds a generated session key and token key and the local MinIO test credentials; `backend/.env.example` holds names and placeholders only. The test suite generates its own session and token keys per run (`tests/conftest.py`).

### 10.2 Commands and results (from `matchdesk-ap/`)

| Command | Result |
|---|---|
| `make test` (drops and re-migrates `matchdesk_test` 0001 to 0006, runs as `matchdesk_app`; Mailpit and MinIO running) | 143 passed, 1 warning (httpx deprecation in Starlette's test client) |
| `cd backend && .venv/bin/pytest -q tests/unit` | 69 passed |
| `cd backend && .venv/bin/pytest -q tests/integration` | 74 passed |
| `cd backend && .venv/bin/pytest -q tests/integration/test_b2_sign_in.py tests/integration/test_b2_files.py` | 11 passed |
| `make check` | exit 0: ruff clean, format clean, mypy no issues, 5 import contracts kept, import rule and float lint clean |
| `make up`, `GET /readyz`, `make down` | ready (database, migrations at head, MinIO bucket); an unauthenticated `GET /api/v1/me` gives 401; stopped cleanly |

### 10.3 Tests that ran

| Test (file `backend/tests/...`) | What it shows | Result |
|---|---|---|
| `integration/test_b2_sign_in.py::test_sign_in_end_to_end_cookie_csrf_reuse_and_logout` | Link requested, read from Mailpit, exchanged by POST; cookie attributes; new session token; mutating request without or with a wrong anti-forgery token refused (403), with it accepted; bearer header refused (401); link reused refused; logout deletes the session and the replayed cookie gets 401; no link token, session token, anti-forgery token or address in the application log | Passed |
| `...::test_link_from_another_browser_is_refused_and_not_consumed` | Other browser 409; the requesting browser then signs in (IT-18 binding) | Passed |
| `...::test_expired_link_is_refused` | Link 11 minutes old refused | Passed |
| `...::test_unknown_address_gets_the_same_answer_and_no_mail` | Same status and body for known and unknown; mail only for the known address | Passed |
| `...::test_rate_limits_address_ip_and_failed_exchanges` | Sixth link for one address: same answer, five mails; 21st request from one IP: 429; 11th failed exchange from one IP: 429 | Passed |
| `...::test_cross_tenant_session_is_refused` | Another tenant's invoice 404 like a missing one; switching to a tenant without membership 404; another session's anti-forgery token refused; cross-origin public POST refused | Passed |
| `...::test_idle_and_absolute_limits` | Idle 58 minutes then extend: works; idle 61 minutes: 401 and the row deleted; past the absolute lifetime: 401 | Passed |
| `...::test_operator_needs_a_one_time_code_used_once` | Operator without code or with a wrong code refused; current code signs in (no tenant, tenant data 404); the same code refused on a later link; seed stored sealed | Passed |
| `...::test_invitation_roles_last_controller_and_deactivation` | Invitation mailed and accepted once with its role; viewer gets 403 on invite, users and match runs; revoked invitation refused; own membership change 403; last controller cannot be demoted (trigger); deactivation ends the user's session at once; audit events written | Passed |
| `integration/test_b2_files.py::test_upload_and_download_for_one_tenant_refused_for_another` | Upload through the API lands in MinIO under `t/{A}/invoice/upload/...{doc}/{sha}.pdf`, no user file name in the key, type sniffed; download for A byte-identical with sandbox headers; B gets 404; signed out 401; B cannot upload into A's batch; `blobstore` refuses A's key for B; anonymous read of the object 403; non-PDF content 415; objects deleted afterwards | Passed |
| `integration/test_b2_files.py::test_blobstore_put_get_delete_round_trip` | Put, get, delete against MinIO | Passed |
| `unit/test_b2_identity_units.py` (9 tests) | RFC 6238 SHA-1 vectors; drift of one step and single use; AES-GCM sealing refuses another key, context or key id; anti-forgery token bound to the session token; permission table; mail fake | Passed |
| `integration/test_tenancy.py` (updated) | `invitations` has forced row-level security and reads zero rows without a tenant; only the two read-only lookup policies exist beyond `tenant_isolation` | Passed |

IT-18 is now partly run (the cases above); still `Not run`: GET of the link page three times (no web page exists; the API has no GET for it) and inspection of the proxy log (no proxy). IT-13 is run only for the endpoints that exist. IT-03 now also runs against MinIO.

### 10.4 OWASP ASVS 5.0.0 requirements

Requirement texts were read on 2026-11-11 from the OWASP ASVS repository at tag v5.0.0 (chapters V3, V6, V7, V8).

Implemented (with the test or code that shows it; see 10.6 for the tests added after the security review): 3.3.1, 3.3.2, 3.3.3, 3.3.4 (cookie attributes; `test_sign_in_end_to_end...`), 3.3.5 (43-character token), 3.5.1 (anti-forgery token plus origin check; `test_sign_in_end_to_end...`, `test_cross_tenant...`), 3.5.3 (state changes only on POST, PUT, PATCH, DELETE); 6.1.1 (TRD 8.1), 6.3.1 (`test_rate_limits...`), 6.3.2 (no default accounts: migrations create none), 6.3.4 (two pathways, both documented in TRD 8.1), 6.4.1 (links and invitations random, expiring, single use), 6.5.1 (links, invitations and TOTP steps used once), 6.5.3 (`secrets`), 6.5.4 (256-bit tokens), 6.5.5 (10-minute links; TOTP 30-second steps), 6.5.8 (TOTP on the server clock), 6.6.2 (`test_link_from_another_browser...`), 6.6.3 (`test_rate_limits...`); 7.1.1 (TRD 8.1), 7.2.1, 7.2.2, 7.2.3 (server-side reference tokens, 256 bits), 7.2.4 (new token at every sign-in; the browser's previous session is deleted, that last part not separately tested), 7.3.1, 7.3.2 (`test_idle_and_absolute_limits`), 7.4.1 (logout test), 7.4.2 (membership deactivation ends sessions, tested; a user with `deactivated_at` is refused on every request, not separately tested), 7.6.2 (a session starts only on an explicit POST); 8.1.1 (schema.md 4.1), 8.2.1 (viewer 403), 8.2.2 and 8.4.1 (cross-tenant 404, row-level security), 8.3.1 (checks in the API and database), 8.3.2 (role read from the membership on every request; deactivation effective at once).

Partly met: 7.4.5 (a controller can end a user's sessions only by deactivating them).

Not met or not applicable: 6.2.1 to 6.2.12, 6.4.2 to 6.4.6 (no passwords, AD-09); 6.3.3 for tenant users (email link only; accepted gap, TRD 8.1); 6.3.5 and 6.3.7 (no security notifications); 6.3.6 (Level 3; email is the factor for tenant users); 6.5.2 (no lookup secrets); 6.5.6 (no way to revoke an operator's authenticator except re-enrolment); 6.8.1 to 6.8.4 (no outside identity provider; OIDC deferred); 7.1.2 and 7.5.2 (no concurrent-session policy or session list; accepted gap); 7.4.3 (no factor-change flow); 7.4.4 (no screens yet); 7.5.1 (no endpoint changes authentication attributes); 13.3.1, 13.3.2 (environment file, not a secrets manager; accepted gap, TRD 8.3).

### 10.5 Documents changed in B2

TRD.md sections 5 (identity may import `audit`), 8.1 (as built: activity resets the idle timer; HMAC anti-forgery token; cookie names; rate-limit storage; no sign-in link for an invitation-only address; operator enrolment; SMTP), the 8.1 ASVS table statuses, 8.7 (as built: S3 store, key format, upload checks); schema.md dictionary (`users.totp_last_step`, `auth_rate_events`) and 9.1 (migration 0006 row, tables built); AGENTS.md (state line, utilities index, commands); R-13 row in section 5; this section.


### 10.6 Security fixes after B2 review, awaiting recheck (2026-11-11)

Review: `_coordination/review/matchdesk-ap-b2-sec-round1.md` (19 attack cases, 7 mutations). Before the fixes the reviewer's script gave 10 passed, 9 failed; mutation mode 1 killed, 6 survived. The fixes below are **security fixes after B2 review, awaiting recheck**: the author recorded them; the reviewer has not retested them.

| Finding | Fix | Regression test (`backend/tests/integration/test_b2_sign_in.py`) |
|---|---|---|
| B2-S01 (major) | An operator account cannot accept an invitation (409). In the data access layer an operator session never carries a tenant: `load_session` drops it, `SessionContext.principal()` returns none, `_issue` and `switch_tenant` refuse it, a database trigger (`sessions_operator_no_tenant`, migration 0007) refuses it, and enrolling a user as operator ends their existing sessions. Support grants are not built, so no path gives an operator tenant data | `test_b2_s01_operator_cannot_enter_a_tenant_through_an_invitation` |
| B2-S02 (major) | Wrong one-time codes count per IP, per link and per account under the locked user row: a link is burned after 3; 5 per account in 15 minutes burns every open link and answers 429 for the window | `test_b2_s02_wrong_codes_are_limited_per_link_and_per_account` |
| B2-S03 (major) | Deactivation revokes the person's open invitations in the tenant and deletes all their sessions; accepting never re-activates a deactivated membership (only a controller's `PATCH /memberships/{id}`) | `test_b2_s06_deactivation_revokes_invitations_and_no_invitation_reactivates` (both orders: invitation before and after the deactivation) |
| B2-S04 | User row locked (`FOR UPDATE`) during the code check, step recorded in the same transaction; link limits counted and checked in one conditional insert under `pg_advisory_xact_lock` on the key | `test_b2_s03_one_totp_step_signs_in_once_under_concurrency` (0 of 8), `test_b2_s04_link_limit_holds_for_parallel_requests` (exactly 5 of 20) |
| B2-S05 | `load_session` deletes a session whose tenant is ended | `test_b2_s07_sessions_end_when_the_tenant_ends` |
| B2-S06 | Rate-limit keys are HMAC-SHA256 under the session key; `requested_ip` no longer written and cleared | `test_b2_s18_no_ip_at_rest_and_rate_keys_are_keyed` |
| B2-S07 | A link request takes at least 40 ms whatever the address, and the membership query runs for unknown addresses too | `test_b2_s16_link_requests_take_the_same_time_for_known_and_unknown` (midpoint classifier under 75%) |
| B2-S08 | Tests that fail when each control is removed: 8.2.1 (M1, M2), 6.4.1 invitation expiry (M3), 7.2.4 (M4), 7.4.2 `users.deactivated_at` (M5), Origin check of 3.5.1 on all three public POSTs (M6) | `test_b2_m1_m2_...`, `test_b2_m3_...`, `test_b2_m4_...`, `test_b2_m5_...`, `test_b2_m6_...` (3 cases) |
| Observation s15 | A code must be six ASCII digits; full-width digits give a clean 401 | `test_b2_s15_non_ascii_code_is_a_clean_refusal` |

Closed afterwards at the lead's request (also security fixes after B2 review, awaiting recheck):

| Item | Fix | Test |
|---|---|---|
| Request-body limit before spooling | `api.limits.BodyLimitMiddleware`, the outermost application middleware: 413 when `Content-Length` exceeds the limit for the path, before a byte is read; without a length, 413 as soon as the streamed count passes it. Limits: upload path 20 MB per file (PDF, PNG, JPEG; `MAX_FILE_BYTES`, TRD 8.7) plus 64 KiB multipart overhead; every other request 1 MiB. The per-type file check stays in the handler | `integration/test_b2_files.py::test_oversize_upload_is_refused_before_anything_is_spooled_or_stored` (Content-Length case: no spool file created; chunked case: refused, spools closed; no document row, no MinIO object; a 1.2 MB JSON body refused; a small upload still accepted) |
| Client address behind a proxy | `api.limits.client_address`: the direct TCP peer, unless it is in `MATCHDESK_TRUSTED_PROXIES` (addresses or CIDR ranges, empty by default); then the right-most `X-Forwarded-For` hop that is not a trusted proxy (a malformed hop counts the proxy itself). Uvicorn runs with `proxy_headers=False`, `forwarded_allow_ips=""` | `unit/test_b2_identity_units.py` (3 tests: untrusted peer ignores the header; right-most untrusted hop; uvicorn options), `integration/test_b2_sign_in.py::test_rate_limit_uses_the_peer_unless_it_is_a_trusted_proxy` (rotating header from an untrusted peer still 429 at 21; behind a trusted proxy each client has its own limit and a client-prepended hop is ignored) |

Not changed (observations of the review, still open): the sealed TOTP seed is not bound to the user ID; the binding cookie value is accepted from the client; the future `/invite` page must ask for confirmation.

Commands and results (from `matchdesk-ap/`, Mailpit and MinIO running):

| Command | Result |
|---|---|
| `make test` (drops and re-migrates `matchdesk_test` 0001 to 0007) | 159 passed, 1 warning (httpx deprecation); after the two items above 164 passed, 1 warning |
| `make check` | exit 0 (ruff, format, mypy, 5 contracts kept, import rule, float lint) |
| Reviewer's script: `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider ../../_coordination/review/matchdesk-ap-b2-sec_attack.py` | 19 passed, 0 failed |
| `... matchdesk-ap-b2-sec_attack.py mutate` | 7 of 7 mutations killed by the repository's own tests |

ASVS 5.0.0 changes against 10.4: 6.3.8 moves to implemented (timing floor; tested); 6.3.1 and 6.6.3 now include per-account limits; 6.5.1 now holds under concurrency; 7.2.4, 7.4.2 and 3.5.1 (origin) now have tests that fail without the control. Documents changed: TRD 8.1 (as built), schema.md (`auth_rate_events`, migration 0007 row), this section.

## 11. C1 corrections 2026-11-11 (lead-checked, not independently reviewed)

An outside review of the go-to-market playbook built from these documents was re-checked by the lead on live sources (`_coordination/review/C1-review-check.md`, `C1-online-checks.md`, outside this repository). The author opened each primary page again on 2026-11-11 where possible; what could not be opened is marked in Decision.md section 13. Owner figures and stop rules were not replaced: inconsistencies are written out with [P] proposals and added to Decision.md section 11 (decisions 9 and 10).

| # | Item | Files changed | Test added | Source |
|---|---|---|---|---|
| 1 | QuickBooks Online has item receipts against a PO before the bill; the Accounting API has no ItemReceipt entity. Item receipts count as class A only when entered by the receiver before the bill by someone other than accounts-payable staff; imported from a report or CSV export. Qualifying question replaced by "Who records the actual quantity when goods arrive? Can we look at one recent PO, its receiving entry and the invoice together?" | Decision.md §2, §3, §4, §5, §11, §12.4, §12.5, §12.7, §13; PRD.md §5, §2, MH-03, §11; TRD.md 8.5, operating cost; schema.md 3.3, 9.1; App-flow.md S-05; design.md §9; execution-plan.md T-0.1.2, T-0.2.5, T-1.1.1, T-3.2.1, §7; `receiving/qbo_item_receipts.py`, `receiving/models.py`, migration 0008 | UT-32 (`tests/unit/test_c1_corrections.py`, 8 cases), IT-30 (`tests/integration/test_c1_receiving_source.py`, 3 cases; the class A insert fails on the old source-type check) | SRC-15 `quickbooks.intuit.com/learn-support/en-ca/help-article/inventory-account/receive-inventory-item-receipt/L5xIhKRpV_CA_en_CA`; SRC-16 `developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/purchaseorder` |
| 2 | Tradogram: Essentials USD 99 a month; receiving (GRN) an add-on on Essentials, included in custom-quote Premium and Scale; ERP / accounting integrations an add-on; QuickBooks Online page claims native integration and PO, receipt and invoice matching. Price gap restated: USD 99 is not the equivalent-feature price | Decision.md §3, §4, §12.7, §13 | Docs only | SRC-20 `tradogram.com/pricing`; SRC-21 `tradogram.com/quickbooks-online` |
| 3 | Funnel against pool: 610 locations in the Vancouver CMA and 889 in BC (NAICS 413, 416, 417; 20–199 employees; June 2026). Targets restated as unique firms, people and messages; unique firms capped at the qualified pool; growth beyond it needs referral partners or other regions ([P], open decision 10) | Decision.md §1, §7.5, §8, §10, §11, §12.3, §12.4, §12.8; execution-plan.md T-0.1.1, T-0.2.2, M0.2 exit; this file F-006 row | Docs only | SRC-18 `www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3310117601`; SRC-19 `...pid=3310117401` (table pages opened; cell values from the lead's note) |
| 4 | Stop rule against forecast: the day-60 expectation is 1.2 paid back-tests while the rule stops below 2. Written plainly with a [P] proposal (stop at day 60 only on zero sales or on replies and calls below 15 and 6; read 2 or more on day 86); owner decides (open decision 9) | Decision.md §9, §11, §12.8; execution-plan.md M0.2 exit | Docs only | Arithmetic: 1 − 0.996³⁰⁰ = 70.0%; 1 − 0.998³⁰⁰ = 45.2% |
| 5 | Break-even display: every summary use of 27 now shows (900 + 6,000) ÷ 256.18 contribution after churn-replacement acquisition, against 24 = 6,900 ÷ 293.68 with no acquisition spend | Decision.md §1, §7.3, §7.5, §8, §12.4; execution-plan.md T-0.1.1; this file F-006 row | Docs only | Decision.md §7.3 arithmetic |
| 6 | Intuit App Partner Program: Builder no fee, 500,000 CorePlus calls a month, blocked above; Silver in Canada $425 a month (currency not printed) with 1,000,000 calls and $4.85 per 1,000 above; approved assessment questionnaire for production; security, technical and marketing reviews for a listing. "Possibly USD 300 a month, unverified" replaced; sensitivity redone (6 and 29 if CAD; 6 and 30 if USD at 1.38) | Decision.md §3, §7.3, §7.5, §13; TRD.md operating cost, risks; PRD.md §11; execution-plan.md §2, T-1.1.1 | Docs only | SRC-17 `developer.intuit.com/app/developer/qbo/docs/get-started/partner-faq` ("Last updated: 2026-10-02"); listing reviews from the program guide via the lead's note (PDF did not render for the author) |
| 7 | Pilot measurement in three separate counts: flagged discrepancy, controller-confirmed overcharge, actual credit recovered | Decision.md §5.1, §9 clause 5; PRD.md MH-12, MH-16, §13 (M-3a to M-3c); schema.md `report_findings`, `finding_outcomes` (proposed, not built); App-flow.md S-13, S-18; design.md §9; execution-plan.md T-0.2.6, T-7.2.2, §7; `reporting/outcomes.py` | UT-33 (`tests/unit/test_c1_corrections.py`, 2 cases) | Lead's note; no external source needed |

Code changes: `matchdesk.receiving` exports `item_receipt_rejection`, `QboItemReceiptRow`, `ItemReceiptRejection`, `QBO_ITEM_RECEIPT_SOURCE`; `matchdesk.reporting` exports `measure_findings`, `FindingOutcome`, `PilotMeasurement`, `OutcomeCount`; migration 0008 widens `receiving_imports.source_type` and adds check `qbo_item_receipt_class_a`. The receiving import job that would apply the row rule (T-3.2.1) and the tables that would store outcomes (`backtest_reports`, `report_findings`, `finding_outcomes`) are not built. Finding statuses did not exist in the code before C1 (exceptions have open, resolved and similar states, not outcome states); the three outcomes are a separate enum and calculation.

Commands and results (from `matchdesk-ap/`, Mailpit and MinIO running):

| Command | Result |
|---|---|
| `make test` before C1 (drops and re-migrates `matchdesk_test` 0001 to 0007) | 164 passed, 1 warning |
| `make test` after C1 (0001 to 0008) | 177 passed, 1 warning (13 new: UT-32 8 cases, UT-33 2, IT-30 3) |
| `make check` | exit 0 (ruff, format, mypy, 5 contracts kept, import rule, float lint) |

Not done: the author did not re-read the Statistics Canada cells or the Intuit program guide; which QuickBooks Online plans offer item receipts and which report exports their creator and creation time remain unverified until T-1.1.1.

## 12. C2 compliance self-check 2026-11-11 (lead-checked, not legal advice)

**Owner decision (2026-11-11, relayed in the lead's round C2 brief):** no lawyer for now. Legal questions are answered by the business's own reading of primary sources in `compliance/self-check.md`, which states at the top that it is not legal advice; the owner accepts the residual risk per question. Recorded as Decision.md section 11 decision 11.

**What was read.** Sources SRC-13, SRC-14 (re-read in full) and SRC-22 to SRC-35, opened on 2026-11-11 by command-line fetch (Justice Laws, BC Laws, OPC, ISED, National DNCL) or in a browser (Intuit, script-rendered). **Not read:** every CRTC page tried (anti-spam FAQ and guide, bulletins 2012-548 and 2012-549, decision 2016-428, Unsolicited Telecommunications Rules) returned HTTP 403 or a "Security Check" page, which was not bypassed. Calling hours rest on a search-result summary only; the CRTC's view of conspicuous publication rests on the lead's C1 note of a law-firm summary.

| # | Question | Self-check section | Residual risk | Gates changed (original text kept) |
|---|---|---|---|---|
| 1 | Cold and warm email (CASL ss. 6, 10(9)(b), 11, 13, 20; SOR/2013-221 s. 4; SOR/2012-36 ss. 2, 3) | 1 | Medium | Decision §11 item 8, §12.4 intro and "Penalty" row; execution-plan §2, M0.2 dependencies, T-0.2.2 acceptance and subtask (a); this file §7, §8 F-028 |
| 2 | Telephone (Telecommunications Act s. 41.7; DNCL business-call exemption) | 2 | Low | Decision §12.4 "Telephone" row |
| 3 | Prospect contact data (PIPEDA s. 4.01; PIPA s. 1) | 3 | Low | PRD §12 |
| 4 | Processing distributor documents (PIPEDA Sch. 1 4.1.3; PIPA ss. 4(2), 34, 35) | 4 | Low to medium | execution-plan §2 letter row, T-0.2.1; PRD §11 |
| 5 | Breach duties (PIPEDA ss. 10.1, 10.3; Intuit s. 13.4) | 5 | Low | TRD §7 incident steps; this file §7 |
| 6 | Intuit developer terms (ss. 3.1, 12.2, 13.4, 20.4; Exhibit A s. 4.4) | 6 | Medium | App-flow S-04 disconnect dialog; schema.md §8 new row; execution-plan §2 Intuit row, T-3.1.1, IT-11; TRD operating cost |
| 7 | Back-test refund terms (BPCPA s. 1; Competition Act ss. 52, 74.01) | 7 | Low | execution-plan T-0.2.1 |
| 8 | "Audit" wording (BC CPA Act s. 47) | 8 | Low | None (new red line) |
| 9 | Foreign rules | 9 | Not applicable while the red line holds | None |

**Templates written (template - adapt):** email footer, referral opener and stop reply (1.3); call opening (2.3); written permission to process documents (4.3); QuickBooks data disclosure (6.3); one-page back-test terms (7.3); "not an audit" report footer (8).

**No-lawyer operating model proposed, each an owner decision [P]:** warm introductions and phone first, cold email only on proven emailable rows (1.6); Phase 0 back-tests worked inside a folder the distributor owns, from reports the controller exports, so MatchDesk holds no QuickBooks login or copy (4.5; decision 12); self-serve upload once the application exists; no foreign outreach except through a local partner (9).

**Facts that changed a design.** (a) Intuit s. 12.2 requires processing to stop when the user revokes consent; S-04 said matching continues on the last copy. Changed to a [P] proposal (decision 12) in App-flow S-04, schema.md section 8, T-3.1.1 and IT-11. No code change: the QuickBooks connection is not built (only `qbo.QboReader` and its fake exist). (b) Intuit s. 20.4 requires insurance; cost unknown (decision 13), noted in TRD operating cost and execution-plan section 2. No other rule changes software already built: sign-in links and invitations are not commercial electronic messages, and outreach is run from the funnel log outside the application.

Commands and results (from `matchdesk-ap/`, Mailpit and MinIO running), after the C2 edits:

| Command | Result |
|---|---|
| `make test` (drops and re-migrates `matchdesk_test` 0001 to 0008) | 177 passed, 1 warning, none skipped |
| `make check` | exit 0 (ruff, format, mypy, 5 contracts kept, import rule, float lint) |

Not done: no independent review of the self-check; CRTC pages unread (above); GST/PST treatment of the back-test not researched (self-check 7.2); the Intuit questionnaire and Data Stewardship and Responsible AI principles named in s. 12.2 were not opened.


## 13. B3 workflows 2026-11-12

Owner request 2026-11-12: stop demos and build the working back end, end to end, on the local stack only (PostgreSQL 16, Redis, Mailpit, MinIO), with no external account. Branch `feat/b3-workflows` from the `feat/b2-local-auth` head. Synthetic data only. Guide: `_coordination/B3-GUIDE.md` (outside this repository).

### 13.1 What was built

| Scope item and task IDs | Built | Partial or deferred (reason) |
|---|---|---|
| 1. QuickBooks read side, M3.1 partial (T-3.1.1 (a) to (d), T-3.1.2 (a) to (d)) | `qbo.QboReader` interface with paging; `RecordedQboReader` over synthetic JSON fixtures in `backend/fixtures/qbo/recorded/` (**shape unverified until T-1.1.1**); sync runs with a cursor saved with each page, upserts on QuickBooks id, bills and credits of the synced vendors with no date filter, resolved PO links of bill lines, `po_change` re-match afterwards; OAuth connect with a random single-use `state` bound to the session, callback, AES-256-GCM sealed tokens with key id, refresh and "needs reconnect", disconnect that erases tokens, sets `delete_after` 30 days out and stops every new sync and match run (self-check 6.4); Intuit endpoints selected by `MATCHDESK_QBO_MODE=intuit` and refusing without a client | Real Intuit client and calls (T-1.1.1 blocked: no developer account); S-04 screen and the 6.3 disclosure (B4); the deletion job that acts on `delete_after` (not built); vendor-credit link by invoice number (no field known until T-1.1.1) |
| 2. Receiving import (T-3.2.1 (a) to (f); T-3.2.2 class B path) | CSV and XLSX upload (content sniffing; XLSX opened only within the TRD 8.7 zip limits, document-type declarations refused, 50,000 rows), evidence class, class A coverage declaration, saved column mappings, row validation with reason and offending value only, **no date-window rejection**, idempotent commit, refused re-upload, void with reason and re-match; QuickBooks item-receipt export rows through `receiving.item_receipt_rejection` with the controller's attested accounts-payable list; class B receiver marks and signer per delivery document (`If-Match`); late lines (an exception open on the PO line) flagged and held for a `late_receipt` approval | Class B extraction of packing slips (T-3.2.2 (a)): delivery documents are imported as transcribed rows, then confirmed; S-05 screen (B4). Commit runs inside the request, not as a job (TRD 6.3 says imports are jobs): accepted for files within the 50,000-row limit, recorded as a deviation |
| 3. Invoice intake and extraction (T-3.3.1, T-3.3.2) | Extraction output becomes invoice and credit-note rows with `read` provenance; vendor identified only by an exact normalised name match, PO only by vendor and normalised number; a passed document requests a match run (`document_ready`); `extraction.LocalPdfExtractor` reads the PDF text layer with `pypdf` (no network, no model), fills only exact patterns and lists what it could not read; gates `required_fields_read` and `subtotal_equals_lines` added beside the B1 arithmetic gates; batch list, per-file states, retry failed (B1 service, now on the API); duplicate-file detection (B1) | Hosted provider adapter (needs an account and no-training terms): `MATCHDESK_EXTRACTOR=provider` refuses to start; evaluation command HR-01 (T-1.1.3); usage events (T-5.1.3 (a)); page-count and pixel limits for images |
| 4. Extraction review API (T-3.3.3 back end) | `GET /invoices` (filters, cursor), review fields with provenance on `GET /invoices/{id}`, `PATCH /invoices/{id}/extraction` (server-side draft, or corrections recorded as `edited` with who, when and the value first read; the document returns to review), `POST /invoices/{id}/confirm-extraction` (gates re-run on stored values; inconsistent only with explicit acceptance); 409 carries the current record; a confirmed correction re-enters matching | Removing a line (lines referenced by results are kept); S-07 screen (B4) |
| 5. Match runs (T-4.1.6, T-4.1.1 (d)) | Triggers for new or corrected documents, receiving commit, void, declaration and class B confirmation, approved late evidence, alias and tolerance changes, duplicate and not-received decisions, QuickBooks sync; all through `request_run` and `matching.evaluate` (rule engine unchanged). **Scope is the affected vendor's invoices**, because a run's fingerprint covers the vendor's whole history; the PO-only scope left an invoice stale (found with the demo data, regression test added). Alias suggestions: earlier alias or SKU first, then `pg_trgm` similarity of the description | Similarity index on `items.name` (built concurrently later, when volume needs it) |
| 6. Exception workflow API (T-4.2.1, T-4.2.3, T-4.2.4, T-4.2.5 back end) | Queue with filters, counters, staleness per row and cursor; resolutions with `If-Match` and allowed codes per type; controller-only "not received" and possible-duplicate decisions; waiver item limit and rolling 30-day cap (also on bulk batch totals) with pending approvals; `receipt_absent` never waived in bulk; withdraw, reopen with history; approvals list and decision for waivers, alias conversions and late evidence, with the self-approval rule; alias create (conversion pending), retire, review acknowledgement; versioned tolerances with preview and re-match; tenant waiver limit and cap | `POST /exceptions/{id}/credit-decision` (needs an engine input for "not credited"; the rule engine was not to be changed); weekly waiver email (the list is the queue filter `status=waived&resolved_since=`); S-08, S-11, S-12, S-15 screens (B4) |
| 7. Report (T-5.1.1, T-5.1.2 back end; T-5.1.3 (c)) | Draft per period with a frozen snapshot in insert-only `report_findings` (sections finding, not received, unverified, waived, open; `reported_amount` per TRD 8.5), qualifying total that a waiver never lowers, coverage by class, supplier-slip-only lines, paid split from QuickBooks bill status, history depth; approval refused while results are stale, approvals or reviews are pending, or lines are unmatched; idempotent; supersedes the earlier approved version; trigger keeps approved versions immutable; PDF (text-only writer `core.text_pdf`) and CSV with the draft mark and the formula-injection guard; refund evaluation from an approved report's stored total | `pilot_engagements` and the governing-report pointer (T-5.1.3 (b)); a tagged, accessible PDF (A11Y-06); stored exports with expiry (exports are generated per request); report stale flag set by later changes (approval re-checks staleness on read instead) |
| 8. One start command (OPS-04) | `make up` checks PostgreSQL and Redis, migrates, starts API and worker, waits for `/readyz`; `make seed-demo` loads one invented tenant: controller and clerk (`.invalid` addresses), connection through the fake authorisation server, a real sync over the recorded fixtures, aliases (one conversion pending), a committed class A receiving file, 12 generated text PDFs and one byte-identical repeat processed by the worker | Compose stack (no Docker on this machine); Redis is checked but not used by the application |

### 13.2 Commands and results (from `matchdesk-ap/`)

| Command | Result |
|---|---|
| `make test` before B3 (branch head `feat/b2-local-auth`) | 177 passed, 1 warning |
| `make test` after B3 (drops and re-migrates `matchdesk_test` 0001 to 0013 as owner, runs as `matchdesk_app`; Mailpit and MinIO running) | 212 passed, 1 warning (httpx deprecation in Starlette's test client) |
| `cd backend && .venv/bin/pytest -q tests/unit` / `tests/integration` | 88 passed / 124 passed |
| `cd backend && .venv/bin/pytest -q tests/unit/test_b3_units.py tests/integration/test_b3_*.py` | 27 passed |
| `make check` | exit 0: ruff, format, mypy (78 files), 5 import contracts kept, import rule, float lint |
| `make down && make up` | database reachable, Redis reachable, migrations at head, API ready, worker running |
| `make seed-demo` (first run, `matchdesk_test` freshly migrated; then `matchdesk_dev`) | tenant created, 13 files uploaded, 32 jobs run; second run: "already exists; nothing changed" |

The demo data was checked by query: FF-1001, FF-1002 and SS-5102 matched; FF-1003 `qty_over_received` 168.00; FF-1004 over-received 8.00 cleared by the QuickBooks vendor credit with no document; SS-5110 `price_variance` 18.00 with the freight line `charge_ok`; SS-5111 re-billing 740.00; IP-301 and IP-302 `alias_unconfirmed` (conversion waiting for the controller); FF-1006 and SS-5120 in review (total does not add up; vendor not printed); FF-1007 `no_po`. An October draft showed findings 926.00, unverified 342.20, qualifying 926.00 and blocked approval for the two reviews, the pending approval and the unmatched line. In `matchdesk_dev` the first seed ran before the fixture PO lines carried a unit (every line `uom_unresolved`); a second sync of the same tenant re-matched it through the `po_change` trigger instead of dropping the database.

### 13.3 Tests that ran (new in B3)

| Test (file `backend/tests/...`) | What it shows | Result |
|---|---|---|
| IT-04 `integration/test_b3_qbo.py::test_it04_*` | Sync idempotent while pending; interrupted after page 1 of purchase orders, resumes at page 2; second run gives the same row counts | Pass |
| IT-11 `integration/test_b3_qbo.py::test_it11_*` | Connect; replayed callback and another session's `state` connect nothing; stored token is ciphertext; refused refresh gives "needs reconnect"; after disconnect tokens are null, `delete_after` is set, sync and match run are refused (409) | Pass |
| UT-14 `integration/test_b3_qbo.py::test_ut14_*` | PO 4390 (14 Aug) is outside the October range, read by reference with its September bill; the October invoice raises no `no_po` | Pass |
| Intuit placeholders `unit/test_b3_units.py` | `intuit` mode refuses without an account; readers have no write method | Pass |
| IT-07b `integration/test_b3_receiving.py::test_it07b_*` | 1,221 rows, 37 invalid with reasons; 1,184 lines imported once; second commit changes nothing; second upload refused; rows dated 2025 accepted | Pass |
| UT-30 end to end `integration/test_b3_receiving.py::test_ut30_*` | Class C slip gives `receipt_absent` / `supplier_slip_only`; class B without marks never passes; with marks and signer (and the late-evidence approval) it matches, counting only the class B line | Pass |
| Void and re-match, item-receipt export (UT-32 rows through the API), XLSX and hostile XLSX | Void needs a reason, result stale at once, then `receipt_absent`; export rows rejected as `creator_unknown`, `entered_by_ap_staff`, `entered_after_bill`; class B export refused; DTD in XLSX refused; binary refused (415) | Pass |
| Local extraction `unit/test_b3_units.py` (UT-08 via the local reader; HR-01 injection case) | Fields read from a generated PDF; an instruction line changes no field; missing fields and images go to review; encrypted PDF fails permanently | Pass |
| Intake and review `integration/test_b3_intake_review.py` | Text PDF read, vendor and PO linked, matched; a document failing the gates is never matched even with a counting receipt (false-pass guard); draft saved on the server; two corrections from one version: one wins, the other 409 with the current record; provenance keeps the value first read; confirmation re-enters matching; inconsistent confirmation needs explicit acceptance | Pass |
| IT-22, IT-14, IT-23 `integration/test_b3_workflow.py` | 20 `receipt_absent` skipped in a bulk waiver, 5 price variances waived, no line becomes `matched`; concurrent resolution 409; clerk cannot confirm "not received" or reopen; controller reopens with the earlier resolution in the events; confirmed "not received" re-matches and becomes a finding | Pass |
| IT-27 | 480.00 of unapproved waivers then 30.00 is pending (cap); 180.00 pending (item limit); ten of 60.00 in bulk all pending (batch total 600.00); waived list by filter; withdraw; approval applies the waiver and the exception stays qualifying | Pass |
| IT-15, IT-21 | Pending conversion gives `alias_unconfirmed` on all three lines; requester cannot approve with a second controller; wrong factor 24 gives over-receipt; retire, create 12, approve: all matched; earlier results superseded and kept | Pass |
| IT-28 | Late class A line does not count until the controller approves; then the exception closes and the line is `late_approved` | Pass |
| T-4.2.5 and T-4.1.1 (d) | Preview counts one cleared exception; clerk cannot edit; each change is a new row, the old one closed, old results keep their rule id; no receipt tolerance; suggestion by earlier alias | Pass |
| Trigger scope regression | An invoice naming an unknown PO is not left stale after a same-vendor document arrives | Pass |
| T-5.1.1, T-5.1.2, IT-17 (a) to (e), UT-11 `integration/test_b3_reports.py` | Totals equal the sum over `report_findings`; draft watermark in PDF and CSV, none once approved; approval idempotent, controller only; refund due below the threshold, not above; waiver keeps the qualifying total; version 2 supersedes version 1 without changing its stored result; approved row and findings cannot be changed or deleted; no-evidence case finding 9.00 and unverified 252.00 (TRD 8.5 example); approval refused while lines are unmatched or results stale; CSV cell `=HYPERLINK(...)` prefixed with an apostrophe | Pass |

Not run: HR-01 evaluation set (no provider), E2E and accessibility tests (no web app until B4), IT-13 over every endpoint (subset only), IT-26 (usage events not built), OPS-04 timing on a clean checkout with a stopped database (the existing failure message was not re-tested in B3).

### 13.4 Deviations from the TRD and schema.md (each is recorded in the document named)

- Module imports (TRD 5): `qbo` imports `matching.normalise_number` (pure); `receiving` reads `qbo` and `intake` models; `intake` reads `qbo` models; `reporting` reads `exceptions`, `intake`, `qbo`, `receiving` models; `api` reads `qbo`, `receiving`, `reporting` models. AES-GCM sealing moved from `identity` to `tenancy.secrets_box` (kernel) so `qbo` can seal tokens; `identity.secrets_box` re-exports it.
- `qbo_connections.refresh_token_enc` is nullable so tokens can be erased at disconnect (checks `tokens_while_connected`, `tokens_erased_on_disconnect`). New tables not in the dictionary before: `qbo_oauth_states`, `receiving_attestations`. New columns: `invoices.field_sources` (header provenance), `approvals.requested_resolution` and `requested_note`, `backtest_reports.created_by` and `supersedes_report_id`, `report_findings.qualifying`, `sync_runs.po_references` and `requested_by`, `receiving_imports.column_map` and `created_by`. `invoices.extraction_run_id` is nullable (fixture rows have none).
- Receiving commit runs in the request (TRD 6.3 lists imports as jobs). Exports are generated per request and not stored as `export` documents.
- Match-run trigger scope is the vendor, not the purchase order (TRD 6.3 updated).
- API additions beyond TRD 12: `GET /exceptions/{id}/events`, `GET /aliases/suggestions`, `GET /reports/backtest/{id}/refund-evaluation`; `PUT /tolerances/default` carries the waiver limit and cap. Not built: `POST /exceptions/{id}/credit-decision`, onboarding, pilot engagements, support grants, audit list, usage, inbound mail, archive export, deletion requests.
- The local extractor is the default in development (`MATCHDESK_EXTRACTOR=local`); tests use the fake.

## 14. B4 web app 2026-11-12

Owner request 2026-11-12: build the screens with the design skills and tools, user-friendly and complete, so the owner can play the whole product as clerk and controller. Branch `feat/b4-web` from the `feat/b3-workflows` head. Synthetic data only. Guide: `_coordination/B4-GUIDE.md` (outside this repository). The design direction followed design.md (tokens of section 5 with a dark counterpart, Inter self-hosted, the calculation sentence as the one emphasised element).

### 14.1 What was built

| Screen group | Built | Partial or not built (reason) |
|---|---|---|
| 1. Shell, S-01, S-02, S-19 | React 18, TypeScript, Vite, React Router, TanStack Query under `web/`; sign-in by emailed link with the development-only Mailpit note; invitation from the link fragment; app frame with navigation by role, QuickBooks status, user menu (sign out, theme, shortcuts, help), idle-timeout dialog, connection-lost banner, page error boundary; signed-out, forbidden, not found; page titles "object · screen · MatchDesk"; focus to the main heading on route change | Tenant switcher shown only with two or more memberships (the demo has one) |
| 2. S-03 to S-07 | Onboarding checklist from live counts; QuickBooks connection with recorded-response mode labelled, read-now with progress, disconnect review; receiving upload, column matching from headers, preview of 20 rows, validation with reasons and download, class A coverage declaration, import, receipt lines with "counts as a receipt", void with reason, class B marks; intake with drag-and-drop and picker, four uploads at a time, totals that add up, per-file states, duplicate file, retry failed; extraction review with PDF.js beside the fields, checks in words recomputed on each keystroke, read and edited tags with history, server-side drafts every 30 seconds, conflict message, confirm and match | App-flow.md section 7 |
| 3. S-08 to S-12 | Queue with filters, sort and selection in the address, per-type counters, coverage strip, J/K/X/Enter, bulk resolve with count, total and per-item results; invoice list; three-pane match view with the calculation sentence, receipts with file, row and class, the QuickBooks billed quantity greyed as not counted, resolve and next in queue order with focus on the next heading, withdraw, reopen, results updating without reload; purchase-order view with timeline; alias map with suggestions, live worked example, retire; approvals with restating dialogs, review of new 1-to-1 aliases, the week's waivers | App-flow.md section 7 |
| 4. S-13 to S-18 | Back-test reports: create and refresh drafts, violet DRAFT and dark APPROVED banners, cards, seven sections, blocking list, approval review with the reviewed-waivers tick, refund calculation on the approved version, PDF and CSV download; tolerances with preview and history; users and invitations with the last-controller rule; audit log with filters, paging and CSV | S-14 weekly summary and S-18 operator console show "not built yet" (no API); support grants not built |

### 14.2 API changes made for the screens (TRD 12, "As built in B4")

`GET /me` carries the anti-forgery token; `GET /qbo/connection` carries the mode; `GET /vendors`, `GET /items`, `GET /audit-events` and its export added; read context added to the queue, invoice detail (match evidence and calculation sentence), batches, aliases, approvals and receiving imports; draft receiving imports return their headers and first rows; the receiving file name is stored in the database only. Three defects found by using the screens were fixed with regression tests: identical files uploaded at the same moment (500, now a duplicate file); the standalone worker failing every document job (identity models not registered); a document left `running` after an unexpected failure while the job's retry skipped it.

### 14.3 Commands and results (from `matchdesk-ap/`)

| Command | Result |
|---|---|
| `make test` before B4 (branch head `feat/b3-workflows`) | 212 passed, 1 warning |
| `make test` after B4 | 221 passed, 1 warning (unit 89, integration 132) |
| `make check` | exit 0: ruff, format, mypy (80 files), 5 import contracts kept, import rule, float lint |
| `make web-check` (`npm run typecheck`, `lint`, `test`, `build`) | type check and ESLint clean; Vitest 11 passed (2 files); build to `web/dist` with no inline script, Mailpit note absent from the bundle |
| `make web-e2e` (Playwright 1.53, installed Chrome, headless; dev server and local API) | 3 passed: E2E-01 full flow, role and not-found check, phone-width check |
| `vite preview` with the TRD 8.7 headers, match view with a PDF | rendered, no Content-Security-Policy violation in the console |
| `make demo-reset`, then the PLAY.md steps in the in-app browser as clerk and controller, with invoices loaded before receiving | completed: receiving 7 rows imported and 1 rejected, 13 files (10 ready, 2 review, 1 duplicate), two extractions corrected, an exception waived, conversion and late evidence approved, October report approved and exported |

### 14.4 Tests that ran (new in B4)

| Test | What it shows | Result |
|---|---|---|
| `backend/tests/integration/test_b4_web_reads.py` (7 tests) | `/me` token equals the session's and is accepted, a wrong one refused, `mode` reported; match evidence: received 60, invoiced 100, "Excess 40 × 4.2 = 168.00.", receipt row 218 counts, QuickBooks billed 100 shown as context only; a line with no receipt reads "Received to date 0." with billed quantity set; queue words and counters; another tenant gets 404 and an empty queue; vendors, items, alias context; audit log controller-only, paged, filtered, CSV, no write route, other tenant empty; receiving file name and draft preview; four identical concurrent uploads give 201 and three duplicates | Pass |
| `backend/tests/integration/test_intake.py::test_unexpected_failure_after_the_lease_releases_the_document` | A failure while storing a result leaves the document `retry_wait`, and the retry succeeds | Pass |
| `backend/tests/unit/test_worker_boundary.py::test_worker_registers_every_model_before_its_first_flush` | Fails without the fix (unresolved `tenants` key), passes with it | Pass |
| `web/src/lib/checks.test.ts` (5) | Cents without floats; 0.1 + 0.2 = 0.30; worked-example arithmetic; checks in words for a line and a total | Pass |
| `web/src/components/components.test.tsx` (6) | Status chips carry a word and never put "Receipt absent" in green; worked example "5 CS × 12 = 60 EA; 50.40 per CS = 4.20 per EA"; batch totals add up; sign-in form validation and the development Mailpit note | Pass |
| E2E-01 `web/e2e/full-flow.spec.ts` | The PLAY.md script automated on a tagged tenant: sign-in through Mailpit, receiving import (7 valid, 1 rejected), 13 files (10 ready, 2 review, 1 duplicate), two corrections, waiver with note, calculation sentence, sign-out, controller approval of the conversion, report draft and approval, draft and approved PDF and CSV downloads, audit log read only | Pass |
| axe-core (WCAG 2.0 to 2.2 A and AA tags) inside E2E-01 | No serious or critical violation on sign in, batch, extraction review, exception queue, match view, approvals, report | Pass |
| Role and phone-width checks | Clerk at `/approvals` sees forbidden; unknown route and another account's invoice are not found; onboarding, approvals, reports, QuickBooks and users at 375 px wide have no sideways scrolling | Pass |

Not run: the manual WCAG checks of design.md section 11 (screen reader, 200% zoom, greyscale), A11Y-06 (tagged PDF), Firefox and Safari, the idle-timeout dialog after a real 58 minutes (the logic ran only by reading), load with 5,000 exceptions.

### 14.5 Deviations

- Screens: App-flow.md section 7.
- API additions and fixes: TRD section 12, "As built in B4"; browser hardening: TRD 8.7, "As built in B4".
- `make seed-demo` no longer uploads the invoices and receiving file: it writes them to `play-files/` (gitignored) so the owner does those steps; `ARGS=--preload` keeps the B3 behaviour. `make demo-reset` added (local `matchdesk_dev` only).
- Playwright runs in the installed Google Chrome (`channel: chrome`) instead of a downloaded browser; each run seeds a tagged tenant that stays in the development database until `make demo-reset`.
- Order matters in the demo: receiving loaded after invoices becomes late evidence needing the controller (B3 rule); PLAY.md loads receiving first and says so.

## 15. B3/B4 review fixes 2026-11-12

Source: the independent review of B3 and B4 (two read-only reviewers, kept outside this repository). Branch `feat/b4-fixes` from `feat/b4-web`. Every finding was first confirmed by reading the code and writing a test that failed on the unfixed code (run by setting the fix aside), then fixed; where a finding was not real, nothing was changed for it and the evidence is given. Back-end tests are in `backend/tests/integration/test_b4_review_fixes.py` unless named otherwise; web tests in `web/src/review-fixes.test.tsx` (Vitest) and `web/e2e/full-flow.spec.ts` (Playwright). New migrations: 0014 (report immutability), 0015 (`po_lines.removed_at`), 0016 (`item_aliases.reviewed_by`, `reviewed_at`); none earlier was edited.

### 15.1 Results

| ID | Finding (short) | Outcome | Test or evidence |
|---|---|---|---|
| C1 | Item-receipt rows without linked-bill audit or attestation counted as class A (false pass #3) | Fixed | `test_c1_review_unknown_linked_bill_is_never_class_a` (unit), `test_c1_item_receipt_export_without_bill_audit_or_attestation_never_counts` |
| M1 | Re-match left a stale pending waiver; decide waived an auto-closed exception; re-request was a 500 | Fixed | `test_m1_rematch_that_closes_the_exception_withdraws_the_pending_waiver`, `test_m1_rematch_that_changes_the_amount_reopens_and_a_new_request_works` |
| M2 | Concurrent waivers passed the period cap | Fixed (advisory lock per tenant and person) | `test_m2_concurrent_waivers_cannot_pass_the_period_cap_together` |
| M3 | If-Match compared without a row lock | Fixed (`lock_for_update` at every site named) | `test_m3_same_if_match_twice_at_once_gives_one_change_and_one_conflict` |
| M4 | Approval of a draft whose results changed after the cut-off | Fixed | `test_m4_approval_refused_when_results_changed_after_the_cut_off` |
| M5 | Approved-report trigger missed columns; findings insertable into an approved report | Fixed (migration 0014) | `test_m5_approved_report_is_immutable_as_a_whole_and_takes_no_new_findings` |
| M6 | Refund evaluated superseded reports; threshold from the caller | Fixed | `test_m6_refund_only_on_the_approved_version_and_threshold_is_not_the_callers`; `test_report_totals_approval_versions_refund_and_export` updated |
| M7 | XLSX cell reference `ZZZZZZZZZZ1` built a huge list | Fixed (column ≤ XFD, ≤ 200 columns) | `test_m7_xlsx_far_column_reference_and_wide_rows_are_refused_quickly` (the unfixed code hung at 100% CPU and was killed) |
| m1 | Reconnecting another company mixed data; realm used elsewhere was a 500 | Fixed (refused, same words as other refusals) | `test_m1_minor_reconnecting_another_company_or_a_company_used_elsewhere_is_refused` |
| m2 | Token refresh not wired; `needs_reconnect` rolled back | Fixed: committed in its own transaction. Wiring: documented as not built (only the Intuit reader needs it, blocked on T-1.1.1) | `test_m2_minor_needs_reconnect_survives_the_callers_rollback` |
| m3 | CSV guard turned negative amounts into text | Fixed | `test_m3_minor_csv_guard_keeps_negative_amounts_numeric` |
| m4 | Non-UTF-8 CSV past 64 KB and bad shared-string index were 500 | Fixed | `test_m4_minor_non_utf8_csv_and_bad_shared_string_are_422` |
| m5 | Concurrent drafts collided (500); approve versus draft race | Fixed (advisory lock per period) | `test_m5_minor_two_drafts_at_once_get_two_versions` |
| m6 | PO lines deleted in QuickBooks stayed matchable | Fixed (migration 0015) | `test_m6_minor_po_line_deleted_in_quickbooks_is_no_longer_matchable` |
| m7 | Uploader chose an evidence class above the attestation | Fixed (commit refused above the attested class) | `test_m7_minor_import_class_above_the_attested_class_is_not_committed`; three B3 tests now attest first |
| W1 | `?from=` unvalidated | Fixed (`safePath`) | Vitest "W1"; E2E-01 `from=javascript:` assertion |
| W2 | Report figures disagreed (list, detail, coverage, approve dialog) | Fixed: "flagged discrepancies" is findings plus not received everywhere; coverage figures labelled on one denominator (the complete-log figure says why it can be higher); the dialog counts every exception still open | Vitest "W2"; E2E-01 list-versus-report assertion; browser walk: 1,037.30 on both, dialog "6 exceptions still open" = queue 6 |
| W3 | Exception strip stale until a draft exists | Fixed (`GET /coverage`) | `test_w3_coverage_is_live_without_a_report_draft`; Vitest "W3"; E2E-01 strip assertion |
| W4 | No "edited" tag after a draft save | Fixed | Vitest "W4 and W8" |
| W5 | "Mark reviewed" never emptied the list | Fixed (migration 0016, invalidation) | `test_w5_mark_reviewed_empties_the_new_alias_list`; Vitest "W5" |
| W6 | Bulk result rows lost names | Fixed (rows kept as chosen) | Vitest "W6"; browser walk |
| W7 | Zero-value "invoiced above ordered" shown; FF-1006 flagged although under-ordered | Engine not wrong: FF-1006 is over the order gross (1,000 on FF-1004 plus 10) and the QuickBooks vendor credit of 100 brings the net to 910, so the engine raises `qty_over_ordered` already `resolved_by_credit` (UT-06 behaviour); the 0.00 rows are the per-line rule of TRD 8.5. Fixed the words: cleared exceptions say "cleared by a QuickBooks vendor credit", amount-less ones show their quantity and "counted under another exception" | `test_w7_engine_flags_over_ordered_only_cumulatively` (passes before and after: evidence); Vitest "W7"; browser walk on FF-1006 and the queue |
| W8 | Session: sign-in loop on cached `me`; polling counted as activity; cache kept after expiry; autosave lost edits typed during save; bulk retry 409 shown as failure | Fixed (all five) | Playwright "an expired session goes to sign-in once…"; Vitest "W8" (background header, cache cleared, autosave); `test_w8_background_requests_do_not_reset_the_idle_timer`; `test_w8_bulk_retry_with_the_same_key_reports_what_was_applied` |
| minor | PLAY 3.3 duplicate direction | Fixed (PLAY.md: the copy uploads first; the duplicate links to it) | Browser walk |
| minor | NarrowNote missing on queue and match view | Fixed | Code (`Exceptions.tsx`, `MatchView.tsx`) |
| minor | `?type=no_po` after the waiver hid the counter and said "no open exceptions" | Fixed | E2E-01 assertion |
| minor | Approvals empty state wrong while aliases wait | Fixed | Vitest "W5" |
| minor | Approved report showed "Refresh draft" | Fixed (only when out of date, as "Create a new draft version") | E2E-01 assertion |
| minor | Unknown record not the S-19 page | Fixed | Playwright "…unknown route is not found" (now asserts the page) |
| minor | "Extraction not confirmed:" empty and stale while matching | Fixed (amount shown; hidden while matching) | Browser walk on FF-1006 |
| minor | "Does not add up" shown when only the supplier is missing | Fixed | Vitest "W4 and W8" |
| minor | Missing labels: invoice filters, "Resolve as", member roles | Invoice filters and "Resolve as": not real (`<label htmlFor="i-state">`, `"i-vendor"` in `Invoices.tsx`; `<label htmlFor="res-code">` in `MatchView.tsx`; the bulk dialog uses a fieldset legend). Member roles: had only `aria-label`; now a `<label>` | Code; phone-width Playwright check (the new label exposed a containing-block overflow, fixed in CSS) |
| minor | Last controller's role select enabled | Not real: `disabled={self \|\| last \|\| …}` in `Settings.tsx` since B4; in the browser the only controller's select has `disabled = true` | Browser walk |
| minor | "4.2" not "4.20" | Fixed (screens and the calculation sentence) | `test_b4_web_reads` updated; Vitest price |
| minor | "1 rows" | Fixed (plural everywhere it was missing) | Browser walk ("Download the 1 rejected row") |
| minor | Receipt-lines table lacked PO line and unit | Fixed | `test_appflow_s05_s16_columns_and_receipt_lines_name_the_po_line` |
| minor | New link in a tab already on `/login/verify` kept the old state | Fixed (restarts on hash change) | Browser walk |
| minor | `note` not reset on Previous/Next | Fixed | Code (`MatchView.tsx`) |
| minor | Every 403 shown as a role refusal, CSRF too | Fixed | Vitest "W8" |
| minor | `next` read after `replaceState` (always "/") | Fixed | Code (`Login.tsx`) |
| minor | PdfViewer render not cancelled | Fixed | Code (`PdfViewer.tsx`) |
| minor | Endless polling on a failing sync GET | Fixed (stops on error after two retries) | Code (`Quickbooks.tsx`, `Onboarding.tsx`) |
| minor | Six `e2e*` folders in `play-files/` | Fixed: deleted; tagged seeds write to the system temporary folder | `play-files/` holds only the demo files after four Playwright runs |
| minor | Silent sign-in rate limit | Kept the anti-enumeration message; the sent message, the development note and PLAY.md now say a link may not come and why; `make demo-reset` empties `auth_rate_events`; tagged test seeds empty it too | Browser walk |
| App-flow | S-01 verify page shows the email | Fixed (address in the link fragment) | `test_appflow_s01_link_carries_the_address_in_the_fragment`; every Playwright sign-in asserts it |
| App-flow | S-05 rows waiting column | Fixed | `test_appflow_s05_s16_…`; E2E-01 |
| App-flow | S-05 receipt lines link to S-10 | Not real: each receipt line's PO cell links to `/purchase-orders/{id}` since B4 (`Receiving.tsx`) | Code; browser walk |
| App-flow | S-06 duplicate row links to the original | Fixed | `test_appflow_s06_s09_…`; browser walk |
| App-flow | S-09 greyed "Billed against PO in QuickBooks" row | Fixed (read from synced bill lines; display only) | `test_appflow_s06_s09_…`; browser walk on SS-5120 |
| App-flow | S-16 last sign-in column | Fixed | `test_appflow_s05_s16_…`; E2E-01 |
| App-flow | S-08 table links carry `from=` | Fixed | Browser walk (link href carries `from=`) |

### 15.2 Commands and results (from `matchdesk-ap/`)

| Command | Result |
|---|---|
| `make test` (clean `matchdesk_test`, migrations 0001 to 0016) | 249 passed (221 before) |
| `make check` | passed (ruff, format, mypy, 5 import contracts, top-level imports, float lint) |
| `web/`: `npm run typecheck`, `npm run lint`, `npm run build` | passed |
| `web/`: `npm test` (Vitest) | 23 passed (11 before) |
| `web/`: `npx playwright test` | 4 passed (3 before) |
| `docs/PLAY.md` walked in the built-in browser as clerk and controller on a fresh `make demo-reset` | Completed; PLAY.md updated where the screens now say more |

### 15.3 Gaps left

- Token refresh is not called by any reader: the only reader that needs it (Intuit) is not built until T-1.1.1.
- The refund threshold is the server's 500.00 until `pilot_engagements` exists.
- A few minor fixes (note reset, PdfViewer, polling, `next`) are covered by code reading and the browser walk, not by a dedicated test.
- Commits: some minor fixes sit in the "web major" and "App-flow" commits because they touched the same files.

## 16. B6 polish 2026-11-12

Source: an outside QA run on `feat/b4-fixes` (0eb643e) and the owner's judgement that the UI looked amateur. Branch `feat/b6-polish` from `feat/b4-fixes`. No migration was added. Design summary and before/after screenshots: [docs/UI.md](docs/UI.md).

### 16.1 Outside QA findings

| ID | Finding (short) | Outcome | Regression test |
|---|---|---|---|
| QA-1 | An invoice whose footer says "Please request a credit note for returned items" was read as `credit_note` with no unread field (the classifier searched the whole text) | Fixed: `extraction.local_pdf.document_type` decides from a heading among the first six non-empty lines ("INVOICE", "TAX INVOICE", "CREDIT NOTE", "CREDIT MEMO") and labelled fields ("Invoice No/Date/Total", "Credit Note No/Date", "Credit Total", "Re Invoice"); free text is never evidence. Conflicting or absent evidence leaves `doc_type` unread, so `required_fields_read` fails and the document goes to review | `backend/tests/unit/test_b3_units.py`: `test_invoice_with_a_credit_note_footer_stays_an_invoice`, `test_true_credit_note_is_read_as_a_credit_note`, `test_the_pair_of_one_invoice_and_its_credit_note_is_told_apart`, `test_conflicting_or_absent_type_evidence_leaves_the_type_unread` |
| QA-2 | Browser QA polluted the dev/demo database: `seed_demo.py --tag` deleted every `auth_rate_events` row and Playwright tenants stayed in `matchdesk_dev` | Fixed: Playwright's global setup runs `backend/scripts/e2e_stack.sh up` (creates `matchdesk_e2e` from scratch, migrates, starts an API on 8102 and a worker with a local file folder), seeds there, and the web dev server for the run listens on 5174 proxied to that API; teardown stops both and drops the database. The seed script deletes nothing (the `auth_rate_events` delete is gone; section 15's "tagged test seeds empty it too" no longer holds) | `web/e2e/global-teardown.ts` fails the run if any table's row count in `matchdesk_dev` differs from before (every run prints "matchdesk_dev unchanged … auth_rate_events included"); `backend/tests/integration/test_b6_seed_isolation.py` (a tagged seed keeps another address's rate events and adds only its own tenant; the seed script contains no delete) |
| QA-3 | `IntuitQboReader.page()` raises `QboNotConfiguredError` | Kept on purpose (not faked). AGENTS.md, docs/PLAY.md and the S-04 screen now say the live connection needs the owner's Intuit developer account and the sandbox check T-1.1.1, and what step remains; the precise TODO list is TRD.md section 11.1 | `test_intuit_mode_is_selected_by_settings_and_refuses_without_an_account` (existing) |

### 16.2 Redesign

One token file (`web/src/styles/tokens.css`: petrol brand scale, graphite neutrals, success, warning, danger, info and review roles, 4/8 px spacing, Inter type scale with tabular figures, radii, shadows, focus ring, light and dark), one component library (`web/src/components/`, 22 Vitest tests in `library.test.tsx`), a grouped collapsible sidebar with counts, a top bar with company, period, QuickBooks status and user menu, and reworked sign-in, onboarding, exception queue, match view, report and intake screens. All other screens take the new look through the same classes. Icons: `lucide-react` 0.468.0 pinned. Behaviour, routes and API calls are unchanged; the B4 Vitest and Playwright selectors still hold except where noted in App-flow.md section 7.

Found and fixed while redesigning: a screen-reader-only label inside a scrolling table was positioned against the page and made `/settings/users` scroll sideways at 375 px (fixed by making each table box the containing block; the phone-width test now names the element that sticks out); the sidebar count was first part of the link's name ("Exceptions 10 open"), now a description; group headings in the sidebar failed contrast (4.2:1, now 6.7:1).

### 16.3 Commands and results (from `matchdesk-ap/`)

| Command | Result |
|---|---|
| `make test` (clean `matchdesk_test`, migrations 0001 to 0016) | 255 passed (249 before) |
| `make check` | passed |
| `web/`: `npm run typecheck`, `npm run lint` (now also `shots/`), `npm run build` | passed |
| `web/`: `npm test` (Vitest) | 45 passed (23 before) |
| `web/`: `npx playwright test` (own stack) | 4 passed; `matchdesk_dev` unchanged |
| `web/`: `SHOTS=after npx playwright test -c playwright.shots.config.ts` | 40 screenshots in `docs/screenshots/after/`; 38 before shots taken with the same harness on 2e99ddb |
| `docs/PLAY.md` walked in the built-in browser (1440 x 900) as clerk and controller after `make demo-reset` | Completed: sign-in through Mailpit; receiving import 7 valid, 1 rejected; 13 invoices, "10 ready, 2 need review, 0 failed, 1 duplicate"; FF-1006 corrected to 0.80 and matched (+10 against received shown red); SS-5120 supplier chosen, QuickBooks billed quantity greyed; queue coverage 75%; FF-1007 waived and the filtered empty state shown; CT-25 conversion approved; October draft approved (qualifying CAD 1,037.30 against the CAD 500.00 threshold: no refund); S-04 states the live-connection status; at 375 px the sidebar opens as a drawer with no sideways scroll. Files were not dragged by hand: the walk fed the play files to the same drop zone and file input from the dev server. Export downloads were not clicked in the built-in browser (no download without the owner's go-ahead); Playwright E2E-01 downloads both exports. PLAY.md updated for the sidebar, the action panel and the theme and period controls |

### 16.4 Gaps left

- The live QuickBooks reader and token endpoint (TRD.md section 11.1).
- Per-file upload progress is shown as waiting, uploading, received or refused; byte-level progress is not measured (the client sends each file in one request).
- The period selector is held in memory per tab (the app keeps nothing in browser storage); a reload starts again at last month.
- Dark theme is checked on S-08 and S-09 screenshots and by token contrast, not by an axe run in dark mode.

## 17. B7 2026-11-13

Source: the read-only A-to-Z review of `feat/b6-polish` (2026-11-13; kept outside this repository) and the B7 brief. Branch `feat/b7-complete` from `feat/b6-polish`. Migration 0017. Part 1 fixes every review finding with a regression test; Part 2 builds the last four pieces.

### 17.1 Review findings

| ID | Finding (short) | Outcome | Regression test |
|---|---|---|---|
| M1 | Match view stayed "Not matched yet" after the first confirm: `stale` was false when a line had no result, so polling stopped | Fixed: `GET /invoices/{id}` reads as pending while a run covering the invoice is queued or running, or while a matchable invoice has a line without a current result; the banner says "Matching… The result appears here without a reload." | `test_b7_review_fixes.py::test_m1_*` |
| M2 | Exception queue table 1231 px in 1146 px at 1440: Status clipped | Fixed: tighter cell padding, supplier names wrap, sub-reasons wrap; no clipped column at 1280 and above | Playwright `tablesFit` on S-08 at 1440 |
| M3 | Review lines table 929 px in 564 px: quantity, unit, price, amount off-screen | Fixed: one block per line; the four arithmetic fields always in view | Playwright `tablesFit` and "Line 1 Unit price" visible on S-07 |
| M4 | Approve dialog "8 exceptions still open", CSV 8 `open`, section 5 "None" | Fixed: one meaning each. Section 5 is "Undecided items" (possible duplicates, possible credits, waiting for approval); the dialog says how many items are still open in the queue and are reported in their sections with their queue status, and how many are undecided; the table column shows the queue status | Visual and Playwright E2E-01 dialog text |
| M5 | "Findings" 1,037.30 in the dialog and 927.30 in the CSV | Fixed: "Flagged discrepancies CAD … (findings CAD … + not received CAD …)" in the dialog, card and PDF; CSV columns `flagged_discrepancies`, `findings`, `not_received`, `unverified`, `qualifying_total_for_refund`; API `flagged_amount` | `test_m5_csv_labels_match_the_screen` |
| M6 | New draft allowed after approval with nothing changed | Fixed in the back end: `create_draft` refuses with 409 when an approved version exists and nothing changed after its cut-off (`changed_since_cutoff`); the screen offers "Create a new draft version" only then; the governing version is chosen once (Part 2) | `test_m6_no_identical_draft_after_approval`; E2E-01 |
| M7 | Audit log overflow, raw JSON and UUID arrays, empty Before column, internal names | Fixed: Time, Who, What happened (action and record in words, history link), Changes ("before → after" per field, identifiers counted as records, dates formatted), first two changes with "Show all" | Vitest `b7-review.test.tsx` (M7); Playwright `tablesFit` and no identifier on S-17 |
| M8 | Phone width: Invoices, Receiving imports, report flagged table overflowed instead of cards | Fixed: those tables and Users, Invitations, Aliases, Approvals and Purchase order stack into labelled cards | Playwright `cardsAtPhoneWidth` on nine screens at 375 |
| M9 | "Credit note number will be sent on request" yielded `credit_note` | Fixed: a type label counts only with ":" or "#" and a value after it | `tests/unit/test_b7_review.py` |
| Minors | Focus after dialogs; bulk dialog pre-selected a code; "read" tag on fields not read; tolerances form; two coverage figures unexplained; date formats; CSV booleans and codes; batch "Reading…" after done, file order, duplicate supplier "Not known yet"; report "By type" order and flagged table order; internal text on customer screens; QuickBooks screen silent in Intuit mode; "Recently approved"; match-view breadcrumb; "Confirmed. Matching…" toast; report width; queue ignored the period, report month read on mount; e2e and screenshots shared Mailpit, database and ports | All fixed. Dates show as "3 Oct 2026" everywhere the app formats them; native date inputs follow the browser's locale and the CSV keeps ISO 8601 on purpose (spreadsheets read it as a date). Each harness now has its own database, ports and Mailpit | Vitest `b7-review.test.tsx`, `review-fixes.test.tsx` (bulk dialog starts empty); Playwright batch text |

### 17.2 Pieces built

| Piece | What | Tests |
|---|---|---|
| Pilot record (T-5.1.3) | `pilot_engagements` per tenant (price, period, refund condition and threshold, signed-terms reference and signer, payment, outcome, version); edited by the operator; shown on S-03 and S-13. A controller chooses the governing approved version once; the refund is evaluated then from that version's stored qualifying total against the record's threshold and stored (trigger refuses changes). The refund evaluation endpoint uses the record's threshold, never the request's. `usage_events`: one unit per invoice or credit note in the Pacific month of first extraction | `test_b7_pieces.py`: pilot and governing version, IT-26; `test_b7_units.py` |
| Weekly summary S-14 (T-5.1.4) | Per supplier for one week; Monday email (worker schedule, `weekly_summary_hour`, once per week) and "Email this week now"; email has totals and a link only | IT-25 and the Monday job in `test_b7_pieces.py`; Vitest; Playwright |
| Operator console S-18 (T-5.1.5) | Accounts, pilot record form, billable units by month, support-access request; grant, decline, end on S-16; read-only support session with banner; operator TOTP sign-in as built in B2 | IT-29 (two tests) in `test_b7_pieces.py`; `test_tenancy.py` allow-list; Vitest; Playwright |
| Email intake (T-3.3.4) | Signed webhook (HMAC over timestamp and body, five-minute window, provider by settings), allowed senders, held messages with release and discard, attachments into an email batch, idempotent on message id, raw message deleted after 7 days; `make demo-email` | IT-12 in `test_b7_pieces.py`; `test_b7_units.py`; Playwright |

### 17.3 Commands and results (from `matchdesk-ap/`)

| Command | Result |
|---|---|
| `make test` (clean `matchdesk_test`, migrations 0001 to 0017) | 276 passed (255 before) |
| `make check` | passed |
| `web/`: `npm run typecheck`, `npm run lint`, `npm run build` | passed |
| `web/`: `npm test` (Vitest) | 54 passed (45 before) |
| `web/`: `npx playwright test` (own stack) | 5 passed; `matchdesk_dev` unchanged |
| `web/`: `SHOTS=after npx playwright test -c playwright.shots.config.ts` | 46 screenshots in `docs/screenshots/after/` (6 new) |
| `docs/PLAY.md` walked in the built-in browser at 1440 x 900 and 375 x 812 after `make demo-reset` | See 17.4 |

### 17.4 PLAY walk

Walked after `make demo-reset` in the built-in browser, 1440 x 900 then 375 x 812 (files attached to the page's file inputs from page JavaScript, sign-in links read from Mailpit's API). Clerk: Getting started shows the pilot terms; receiving import "7 rows valid, 1 rejected", 7 imported; 13 invoices, "13 files read: 10 ready, 2 need review, 0 failed, 1 duplicate", files in name order; FF-1006 total corrected to 0.80 with the "edited" tag and one "not read" field; after **Confirm and match** the match view showed "Matching…" and then "Invoiced above received" without a reload, and SS-5120 after choosing its supplier went from "Matching…" to its result (M1); the queue table measured 1146 px in a 1146 px box; FF-1007 waived and the filtered queue said 'No open exceptions of type "No purchase order".'. Controller: landed on Approvals; conversion approved, aliases marked reviewed; draft for October with no blocking reason; approve dialog "Flagged discrepancies CAD 1,037.30 (findings CAD 927.30 + not received CAD 110.00)", section 5 "Undecided items"; approved; no new-draft button, and a new draft through the API was refused with 409; version 1 made governing: "Qualifying discrepancies CAD 1,037.30 against the threshold CAD 500.00: no refund"; CSV header `flagged_discrepancies,findings,not_received,…` with `1037.30,927.30,110.00`; weekly summary for 5 to 11 October; audit log in words with no identifier, fitting its box; `make demo-email`: one accepted into an Email batch, one held, released. Operator: TOTP sign-in with `make operator-code`; console with pilot, payment and 14 billable units; pilot record saved (threshold field fixed after the governing choice); access requested; `/invoices` returned to the console. Controller granted 1 day on Users and access. Operator at 375 px: opened the account read only (banner with the end time, no resolve control, no sideways scroll) and left it (`/api/v1/invoices` then 404). At 375 px, nine reading screens (Getting started, Users, Weekly, Intake, Invoices, Receiving, Audit, Approvals, the report) had no sideways scroll and every list table was stacked into cards. Wording fixed after the walk: an active grant now reads "has 1 day of read-only access"; the audit log names "Governing report version chosen". Observed and noted: with four uploads at a time, which of the two identical FF-1002 files becomes the duplicate depends on which arrives first (PLAY.md now says so).

### 17.5 Gaps left

- Account-bound: the live QuickBooks reader (TRD.md section 11.1); a hosted extraction provider and its region highlighting; a hosted inbound email provider (only the local signed webhook is built).
- Not account-bound, not built in B7: the "no receiving records" declaration on S-03; deleting an invoice line on S-07; pre-applying a saved receiving mapping and the seven-day removal of abandoned previews on S-05; the S-08 assignee filter; the S-10 "changed in QuickBooks" banner; the note on an inconsistent document; credit decisions; finding outcomes (`finding_outcomes`); deletion requests and archive export.
- The weekly summary schedule runs inside the worker every minute (no external scheduler); two workers would each try, and the unique key lets only one send.

## B8 2026-11-13

Source: the owner's brief of 2026-11-13 (role-based redesign and financial-trust fixes; kept outside this repository). Branch `feat/b8-redesign` from `feat/b7-complete`. No migration. Evidence: [docs/screenshots/b8/](docs/screenshots/b8/README.md) (before and after on the same seeded records, state log, measurements).

### B8.1 Baseline walk (before any change)

Walked on the owner's demo (`matchdesk_dev`, PLAY.md already played) in the in-app browser of the Claude desktop app; both connected Chrome extensions were on other computers that cannot reach this machine's 127.0.0.1. The decision step ran on the screenshot stack, not on the demo. Findings rechecked against the checkout:

| ID | Finding at the baseline | Confirmed how |
|---|---|---|
| B8-1 | Weekly drill-down dropped the week: S-14 linked `/exceptions?vendor=…`; the queue took its dates from the top-bar month. S-14 said 1 exception, CAD 168.00 for Fictional Fasteners; the queue showed 2, CAD 168.80 (demo) or CAD 330.00 (screenshot stack) | Browser on the demo; `before/measurements.json` |
| B8-2 | Queue filters and sorts ran in the browser over the rows loaded so far (200 per request, cursor on the id only); the match view rebuilt its own order from one page of 200 without the month | Code: `Exceptions.tsx`, `MatchView.tsx` `queueOrder`, `exception_routes.py` |
| B8-3 | A fresh account's coverage read "0%" or "Not measured" with no reason; the weekly summary of an empty week showed CAD 0.00 cards | Code; S-14 at the baseline |
| B8-4 | The header said "QuickBooks connected" with a green dot in recorded-response mode; the S-04 read status lived only in page memory | Browser |
| B8-5 | At 375 x 812 the first case's link started at 1,528 px | `before/measurements.json` |
| B8-6 | FF-1003's receipt link sat 855 px down in a separate panel and opened the whole import, not the row | `before/measurements.json`, browser |

### B8.2 Trust fixes and their tests

| Fix | Test |
|---|---|
| Queue as one ordered set: every filter (status, type, sub-reason, supplier or none, dates, value range) and the sort applied in the database before the page is cut; keyset cursor on the full sort key with the id as tie-break; count and value of the whole scope (`api/queue.py`) | `test_b8_trust.py::test_queue_sorts_and_filters_the_whole_set_before_the_page` (230 rows: the largest amount, inserted last, leads page 1; ten equal values in id order; no row repeated or skipped across the cursor; value filter across the set; exact decimal total) and `test_type_counters_ignore_the_type_filter` |
| Match view previous and next from `GET /exceptions/{id}/neighbours` with the same scope; works after the exception left the set | `test_neighbours_follow_the_opened_order_beyond_row_200` (row 205; last item; after resolution); Vitest `b8-trust.test.tsx` (queue to case and back); Playwright `queue-b8.spec.ts` |
| Weekly drill-down carries `from`, `to`, supplier (or none) and status; the queue shows the active dates as a chip and keeps them on open, Next, Back, Refresh and when one filter is removed | `test_weekly_drilldown_scope_equals_the_report` (inside 7 October counted, 22 October not: 1, CAD 168.00 both sides); Vitest; Playwright |
| Empty versus zero: measurement state on live coverage and the weekly summary; figures only when measured | `test_empty_is_not_zero`; Vitest; Playwright (empty week) |
| QuickBooks status from the server: source Demo data, last sync with failure | `test_quickbooks_status_is_the_servers`; header and S-04 |
| Approvals carry the lines a conversion re-matches | `test_conversion_approval_lists_the_lines_it_rematches` |

No float was added; amounts stay `NUMERIC` in the database and decimal strings in the browser. No write to QuickBooks. No change to matching, `receipt_absent` or the refund calculation.

### B8.3 Redesign

S-08 queue, S-09 match view (ledger line, receipt row link, consequence, one decision per click, PDF fit width and expanded view), S-12 approvals, S-13 reports, S-14 weekly summary, S-05 receiving check, S-06 batch, S-07 total check, S-03 next task, S-17 audit log, S-18 operator account, header and support banner. Details in [docs/UI.md section 6b](docs/UI.md) and [App-flow.md section 7](App-flow.md#7-as-built-in-b4-2026-11-12).

### B8.4 Commands and results (from `matchdesk-ap/`)

| Command | Result |
|---|---|
| `make test` (clean `matchdesk_test`, migrations 0001 to 0017) | 283 passed (276 at B7; 7 new in `test_b8_trust.py`) |
| `make check` (ruff, format, mypy, import contracts, top-level import rule, float lint) | passed |
| `web/`: `npm run typecheck`, `npm run lint`, `npm run build` | passed |
| `web/`: `npm test` (Vitest) | 59 passed (54 at B7; 5 new in `b8-trust.test.tsx`) |
| `web/`: `npx playwright test` (own stack `matchdesk_e2e`, 8102, 5174) | 8 passed (5 at B7; 3 new in `queue-b8.spec.ts`); `matchdesk_dev` unchanged |
| `web/`: `SHOTS=before` and `SHOTS=after npx playwright test -c playwright.shots.config.ts b8` (`matchdesk_shots`) | 16 before and 20 after screenshots, `measurements.json` each |
| `make demo-reset`, then API, worker and web left running | see B8.6 |

### B8.5 Measured, before and after (same seeded records and viewport)

| Measure | Before | After |
|---|---|---|
| First actionable case at 375 x 812 | link at 1,528 px, not visible | case at 300 px, its Review control at 387 to 427 px, visible and clickable (Playwright: not covered, opens the case) |
| Weekly summary 5 to 11 Oct against the queue it opens (Fictional Fasteners) | report 1, CAD 168.00; queue 2, CAD 330.00 | report 1, CAD 168.00; queue 1, CAD 168.00 |
| FF-1003 receipt at 1440 x 900 | 855 px down, opens the whole import | 247 px down beside "Received 60 EA", opens row 4 marked |

### B8.6 Walk after the change

In the in-app browser on the demo (no mutation) and in installed Google Chrome through Playwright on the isolated stacks: keyboard-only (J, K, Enter opened FF-1003 with focus on its heading; the row is focused again on return), 1440, 1024 and 375 wide in light and dark with the invoice PDF on screen, the weekly drill-down, a waiver's consequence before submission, partial data (SS-5120 with no supplier), a clerk on /approvals (forbidden), and the operator's read-only visit (banner, no Resolve control, Leave the account). Live integrations: none verified; everything ran on synthetic data and recorded QuickBooks responses.

### B8.7 Gaps left

- Unchanged from 17.5 (account-bound and not-built items).
- Extraction review, the receiving column step, intake upload, aliases and tolerances still ask for a wider window at phone width (reading stays possible).
- The match view opens the PDF on the line's page only when the extractor recorded it; the local extractor records none, so it opens on page 1. The S-07 total check does not point at a region of the page (no regions are recorded).
- The sidebar's return to the last queue lives in memory for the tab; a reload returns to the unfiltered queue (the address bar keeps the scope).

## B9 2026-11-13

Source: the owner's request of 2026-11-13 to build everything left that needs no outside account (brief kept outside this repository). Branch `feat/b9-remaining` from `feat/b8-redesign`. Migrations 0018 and 0019. Account-bound items stay out: the live Intuit reader, a hosted extractor with region highlighting, a hosted inbound email provider.

### B9.1 Items and their tests

| Item | What was built | Tests |
|---|---|---|
| S-03 no receiving records | Controller records "We have no warehouse receiving records" (`no_receiving_declarations`); audited; step 3 reads "None kept"; coverage state `no_receiving_records` (a measured 0 %) on S-05, S-08 and S-13 instead of "awaiting receiving"; report totals and PDF state it. Lines stay `receipt_absent` (never a pass, CLAUDE.md false pass 2); refused while an import counts; committing an import withdraws it (audited). Also: S-03 names the attestation and lists "earlier invoices needed" | `test_b9_remaining.py::test_no_receiving_declaration_is_recorded_and_never_a_pass`, `test_onboarding_status_names_the_attestation_and_the_earlier_invoices_needed`; Vitest S-03; Playwright fresh-account declaration |
| S-07 delete a line | Soft removal (`invoice_lines.removed_*`) with who, when, why; gates re-run; earlier results kept, current one retired; only before confirmation; number never reused; every match input, gate, count and screen reads live lines | `test_remove_line_is_soft_reruns_gates_and_only_before_confirmation`; Vitest S-07 (two tests) |
| S-07 inconsistent note | Required with "The document itself does not add up"; stored on the invoice, in the audit event, report section 6 and the PDF | `test_inconsistent_note_is_kept_shown_and_reported`, updated `test_inconsistent_confirmation_needs_explicit_acceptance`; Vitest |
| S-05 mappings and drafts | `GET /receiving/mappings`; a saved mapping whose columns fit the file is pre-applied (rows still checked only on request); drafts removed after 7 days by the worker (file deleted through `blobstore`, audited) | `test_saved_mapping_is_read_and_pre_applied`, `test_abandoned_drafts_are_removed_after_seven_days_with_a_frozen_clock` (`FixedClock`) |
| S-08 assignee | `exceptions.assigned_to` (index built concurrently, 0019); assign or unassign (event `assigned`, audited); `assignee` (`me`, `none`, member) in the server scope, keyset cursor and neighbours; kept in the URL; bulk assign | `test_assignee_filter_is_in_the_scope_cursor_and_neighbours`; Vitest; Playwright assignee and reload |
| S-10 changed in QuickBooks | The sync records `po_line_changes` (before and after) for changed or removed lines; S-10 banner when matched lines changed, with when they were matched again; proved on recorded responses (`fixtures/qbo/recorded-changed/`, `make demo-po-change`) | `test_changed_in_quickbooks_banner_from_recorded_responses`; Vitest S-10; Playwright S-10 |
| Credit and duplicate decisions | `POST /exceptions/{id}/credit-decision` and `/duplicate-decision` (controller); the credit decision is a rule-engine input: credited nets that one credit with that one exception, once; not credited is a finding again and never re-flagged by that credit; undecided stays open, not a finding | `test_credit_decision_nets_once_and_not_credited_is_a_finding`, `test_duplicate_decision_endpoint_is_controller_only`; `tests/unit/test_b9_units.py` (4, order independence included); Vitest; Playwright S-09 |
| Finding outcomes | `finding_outcomes` insert-only with trigger rules (governing version only, confirmation ≤ finding, recovery needs and ≤ confirmation, a credit note or reference); S-13 section 8 and the three counts kept apart; report figures unchanged | `test_finding_outcomes_follow_the_governing_report_and_stay_separate`; Vitest S-13; Playwright S-13 |
| Archive and deletion | Archive ZIP (originals and CSVs incl. audit log) built by the worker, downloadable 24 hours, audited; account deletion request (name typed), operator schedules (30 days' notice [assumption]) or declines on S-18, controller may cancel; when due the worker deletes files, then `purge_tenant` deletes every row and writes `deletion_ledger`; the app role cannot purge early nor delete insert-only rows | `test_archive_export_holds_records_and_originals_and_expires`, `test_account_deletion_request_operator_schedule_cancel_and_execute`; Vitest S-16; Playwright archive, request, schedule, cancel |
| Phone width | S-07, S-05 column step, S-06 upload, S-11, S-15 worked at 375 x 812; "Open in a wider window" removed | Playwright five screens at 375 (no sideways scroll, controls visible) |
| Queue link after reload | Sidebar Exceptions link kept in sessionStorage (queue path and scope keys only; try/catch, memory fallback) | Vitest (two tests); Playwright reload |
| S-12 late evidence | Lists the exceptions open on its PO lines with their value | `test_late_evidence_approval_lists_the_open_exceptions_it_lets_the_rematch_see` |

No float added; no write to QuickBooks; no change to the `receipt_absent` guards; approved reports stay immutable (outcomes are separate rows).

### B9.2 Commands and results (from `matchdesk-ap/`)

| Command | Result |
|---|---|
| `make test` (clean `matchdesk_test`, migrations 0001 to 0019) | 306 passed (283 at B8) |
| `make check` | passed |
| `web/`: `npm run typecheck`, `npm run lint`, `npm run build` | passed |
| `web/`: `npm test` (Vitest) | 72 passed (59 at B8; 13 new in `b9-remaining.test.tsx`) |
| `web/`: `B9_SHOTS=1 npx playwright test` (own stack `matchdesk_e2e`) | 14 passed (8 at B8; 6 new in `remaining-b9.spec.ts`); `matchdesk_dev` unchanged; 12 screenshots in `docs/screenshots/b9/`. Two earlier runs that day had one timeout each while the screenshot stack and the in-app browser ran on the same machine (once B7's "Email now" dialog, once a sign-in); both passed on the next run with nothing changed |
| `make demo-reset`, then API, worker and web left running | done |

### B9.3 Walk

In the in-app browser on the screenshot stack (`matchdesk_shots`, a tagged synthetic tenant), at 1440 x 900 and 375 x 812: SS-5110 line 2 removed with a reason ("Lines + tax = 758.00, document total 783.00"), confirmed with the note, note shown on the match view; `po-change` on that stack: PO 4471 banner "Line 1: Ordered 100 → 80", matched again; FF-1003 "Possibly credited in QuickBooks" (VC-DEMO-9), **Credited**, then "Credited in QuickBooks (VC-DEMO-9), decided by the controller", not qualifying; the five former wide-only screens, S-03, S-05, S-08, S-10, S-12 and S-16 at 375 with no sideways scroll. The remaining features were walked through Playwright in installed Chrome (screenshots in `docs/screenshots/b9/`).

### B9.4 Gaps left

- Account-bound, unchanged: live QuickBooks reader (T-1.1.1), hosted extractor and region highlighting, hosted inbound email provider.
- Not built, not account-bound and not in this request: deleting a single document (`POST /documents/{id}/deletion-requests`), `GET /usage` for the controller, draggable pane dividers on S-09 (a B6 layout choice).
- The account purge relies on a security-definer function owned by the migration role; its execution was tested on the local database only. Backups keep deleted data up to 56 days (schema.md 8).

## B10 2026-11-13

Source: the outside deep-QA pass on `main` 7206efb (brief `_coordination/B10-GUIDE.md`, kept outside this repository). Branch `feat/b10-hardening` from `main` 7206efb. Migrations 0020 and 0021. Every item below was fixed; none was found not real. "Before" means the new test was run against 7206efb (a worktree of `main` with the B10 test files copied in; names B10 added were stubbed so the file loads) and failed there.

### B10.1 Findings, fixes and tests

| # | Finding | Fix | Test (failed on 7206efb, passes now) |
|---|---|---|---|
| 1 | Unreadable original: archive `ready`, 0 originals, HTTP 200 | `expected_count`, `included_count`, `missing_count`; state `incomplete`, never `ready`; **Retry missing files** rebuilds it and replaces the ZIP; README says INCOMPLETE; S-16 "Complete: n/n" or "Incomplete: n/m"; the deletion dialog and the operator's row show the latest verified archive. Decision: deletion may proceed without a complete archive only with the controller's explicit acknowledgement (stored, shown to the operator). Playwright on the branch also found that a byte-identical duplicate upload (intake stores no second copy) read as missing; it is now listed as the earlier file | `test_archive_with_unreadable_original_is_incomplete_and_retry_completes_it` (before: `'ready' == 'incomplete'`), `test_deletion_without_complete_archive_needs_acknowledgement_shown_to_operator` (before: 201, not 409), `test_a_byte_identical_upload_is_the_earlier_file_not_a_missing_one`; Vitest item 1 (two) |
| 2 | Cancel accepted while the worker removes files | The worker claims a due deletion (`deleting`, one conditional `UPDATE`, committed) before the first file; cancel is one conditional `UPDATE` on `requested`/`scheduled` and is refused with "already running"; `purge_tenant` needs the claim; Scheduled, Deleting and Cancelled distinct on S-16 and S-18 | `test_cancellation_during_file_removal_is_refused_and_the_deletion_finishes` (before: cancel accepted mid-removal, then `purge_tenant` "no deletion is due": files gone, account kept), deterministic interleaving `test_cancel_read_before_the_claim_cannot_win_after_it`, `test_cancel_before_the_claim_wins_and_nothing_is_removed`; Vitest item 2 (two) |
| 3 | Pasting `1,000` crashed S-07 (BigInt) | `parseNumberInput` (web) and `parse_typed_decimal` (backend), one rule: separators only between groups of three before a dot; `1.000,5`, `1,5`, letters, exponents, NaN, lone minus, oversize refused with the reason beside the field; checks run on plain values; values sent plain; helpers never throw. Audited: tolerances, waiver limits, alias conversion and example, queue value filter, pilot price and threshold, outcome amount; receiving files and the local PDF reader read `1,5` as 15 before (now refused) | Shared fixture `backend/fixtures/decimal_cases.json` (29 typed inputs) in `test_b10_decimal.py` and `decimal-shared.test.ts` (before: every typed case failed, the parser did not exist), `test_local_reader_does_not_guess_a_comma_decimal` (before: 15); Vitest review paste test; Playwright `B10 pasting 1,000 and 1.000,5 into the review screen keeps the form open` |
| 4 | `-1 × 1.235 = -1.23` on the web | `scale()` rounds half away from zero (as Python `ROUND_HALF_UP`). Backend `core/money.py` was already right (the 28 shared line-amount and cents cases passed on 7206efb); four other backend places used `quantize()` without a rounding mode (half even): report coverage percent, weekly pass rate, alias suggestion score, queue total; now half up | Shared fixture: 19 line amounts and 9 cent roundings, positive and negative, credit notes, fractional prices, half-cent boundaries (before on the web: 7 failed, e.g. `-.50` for `-0.51`); `test_percentages_round_half_up_not_half_even` (before: 3.12 for 3.13) |
| 5 | Weekly email lost after a mail failure | `weekly_summary_deliveries` per recipient: pending, sent (after the mailer accepted), failed; a retry sends only to pending or failed; audit `weekly_summary.sent` with what was delivered, or `weekly_summary.failed`; the schedule retries up to 5 attempts [assumption]; S-14 shows delivery per run and **Retry the failed recipients** | `test_weekly_email_lost_after_a_mail_failure_is_sent_on_retry`, `test_send_now_retries_the_failed_recipients_of_the_scheduled_email` (before: the error escaped and the run was recorded as sent); Vitest S-14 delivery |
| 6 | Empty week email said CAD 0.00 | One rule `measurement_words()` for the email, S-14, the S-08 coverage line and the report CSV and PDF: unmeasured states say why ("No invoices checked for this week") | `test_empty_week_email_says_no_invoices_checked_not_cad_zero` (before: "Documents: 0 … CAD 0.00"); Vitest empty week; B8 tests updated to the shared words |
| 7 | Stale worker overwrote a newer job result | The claim's attempt number is its token; the final and the retry update require it and `running`; an expired claim's result returns `superseded` | `test_expired_claim_late_failure_does_not_overwrite_a_success` (before: `failed` overwrote `succeeded`) |
| 8 | One failing scheduled task blocked the others | `run_operations()`: each operation with its own error handling; `scheduled_operations` (global) keeps last start, success, failure, error class, consecutive failures; S-18 **Operations** panel, failing then late (10 minutes [assumption]) first | `test_a_failing_weekly_email_does_not_stop_the_other_scheduled_operations` (before: the four others never ran); Vitest Operations |
| 9 | Toasts defaulted to success; errors toasted as success | Tone required (`success`, `error`, `info`), every call fixed; errors stay until dismissed; failed downloads (archive, audit export, report PDF and CSV, original document) show the reason and **Retry download** inline | Vitest guard that scans every source file (on 7206efb it lists 5 calls: AccountData, Audit, Exceptions, Intake, Reports), error toast persistence and limit, inline download retry |
| 10 | Reports and receiving fetched the first 200; invoices paged by id, sorted in the browser | Keyset paging in the order shown with an id tie-break (`api/paging.py`): invoices by document date and number, reports by period and version (newest first), receiving imports newest first; UI pages them all ("Show older …"); the PO and credit-note pickers read every page; the ignored `doc_type` filter now works | `test_invoices_page_in_document_date_order_across_201_plus` (205 invoices, pages of 200 and 37), `test_reports_and_receiving_imports_page_in_display_order_across_201_plus` (203 reports, 204 imports) (before: out of order) |
| 11 | S-09 credit decision facts scattered, effect unstated | Invoice, candidate credit, supplier, amount and why it is only possible grouped beside the choice; the chosen decision's effect stated ("Credited: CAD 168.00 nets against VC-DEMO-9 and leaves the findings.") before **Confirm** | Vitest item 11; B9 Vitest and Playwright updated to choose then confirm |
| 12 | Mobile extraction review | Total check one line when it agrees; on a mismatch both amounts, the exact difference, the field to check and each source; validation errors beside each field | Vitest item 12 and item 3; Playwright walk at 375 |
| 13 | Receiving mapping without sample values | Each mapping shows a value from the file; required unmatched first; optional folded with a count | Vitest item 13; Playwright walk |
| 14 | Aliases and tolerances without a live example or consequence | "1 CS → 25 EA" as typed, last valid example kept with a label; beside the save buttons: lines affected and whether they wait for approval (aliases), the re-match preview while typing (tolerances) | Vitest item 14 (two) |
| 15 | Operator console order | Requests needing the operator first (oldest first), then deleting, then scheduled by date; each row: account, requesting controller, effective date, archive completeness; account creation folded at the bottom | `requested_by_name` asserted in the acknowledgement test; Vitest item 15 |
| 16 | Reports and recovery outcomes | Scope and the three totals above the outcome rows; each row a permanent state and its next step; toasts at the top, at most two | Vitest item 16 (two, one reads the CSS rule) |

No float added; no write to QuickBooks; no change to the `receipt_absent` guards; approved reports stay immutable (the measurement state is written into `totals` only when a draft is created).

### B10.2 Commands and results (from `matchdesk-ap/`)

| Command | Result |
|---|---|
| `make test` (clean `matchdesk_test`, migrations 0001 to 0021) | 380 passed (307 on 7206efb) |
| `make check` | passed |
| `web/`: `npm run typecheck`, `npm run lint`, `npm run build` | passed |
| `web/`: `npm test` (Vitest) | 150 passed (72 on 7206efb; 19 in `b10-hardening.test.tsx`, 59 in `lib/decimal-shared.test.ts`) |
| `web/`: `B10_SHOTS=1 npx playwright test` (own stack `matchdesk_e2e`) | 16 passed (14 on 7206efb; 2 new in `stability-b10.spec.ts`: the paste test and the walk of the changed screens at 1440 and 375 with axe); `matchdesk_dev` unchanged (checked by the teardown); 16 screenshots in `docs/screenshots/b10/`. The first branch run found the duplicate-upload archive case (item 1) and two text changes, fixed before the passing run |
| `make demo-reset`, then API, worker and web left running | done |

### B10.3 Walk

Playwright walked review with a mismatch, the receiving mapping, aliases, tolerances, the weekly summary, report outcomes, account data and the operator console at 1440 x 900 and 375 x 812 with no sideways scroll and no serious axe finding (screenshots in `docs/screenshots/b10/`). After `make demo-reset`, in the in-app browser on `matchdesk_dev` without changing anything: the deletion dialog at 1440 shows "Latest archive: No archive prepared" and the required acknowledgement; aliases at 375 with `2,5x` show the reason beside the field and keep the last valid example; tolerances at 375 show the example and "Saving re-matches 0 lines" beside the button, no sideways scroll. The web dev server on 5173 had stopped proxying `/api` after the API restart and was restarted (`make web`).

### B10.4 Left

- Account-bound, unchanged: live QuickBooks reader (T-1.1.1), hosted extractor and region highlighting, hosted inbound email provider.
- The unique index on open deletion requests still covers `requested` and `scheduled` only; `deleting` is treated as open in code (changing the index needs a concurrent rebuild in its own migration).
- Assumptions: 5 delivery attempts per recipient by the schedule, 10 minutes before an operation counts as late, 15 minutes before a stopped deletion claim is taken over.
- The database `matchdesk_depth_137206` (the outside QA's leftover) was not touched.
