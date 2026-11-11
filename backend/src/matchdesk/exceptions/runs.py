"""Match runs: scope, fingerprint, job, supersede (T-4.1.6; TRD 6.3).

Reuse rule (B1-001): a request is answered with an existing run only when that
run has identical inputs AND is still the current run for every line in scope
(or is still pending with identical inputs). Returning to an earlier input
state (a receipt removed, a credit voided, a value changed back) therefore
creates a new run that supersedes the newer result; the stored result always
equals ``evaluate()`` on the current inputs once the run has executed.

Ordering (B1-011): ``execute_run`` takes a per-tenant advisory transaction lock
before reading inputs, so two runs never evaluate and store concurrently; the
run that stores last read its inputs last.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from matchdesk.core import get_correlation_id, get_logger, new_correlation_id
from matchdesk.exceptions.inputs import build_match_input
from matchdesk.exceptions.models import LineMatch, MatchRun, RulesetVersion
from matchdesk.exceptions.store import store_result
from matchdesk.intake.models import InvoiceLineRow
from matchdesk.matching import evaluate, input_fingerprint
from matchdesk.tenancy import PermanentJobError, enqueue, transition

log = get_logger("matchdesk.match_runs")
TASK = "match_run"
PENDING = ("queued", "running", "retry_wait")


def _ruleset_id(s: Session, code: str) -> uuid.UUID:
    rid = s.scalar(select(RulesetVersion.id).where(RulesetVersion.code == code))
    if rid is None:
        raise PermanentJobError(f"rule set {code} missing")
    return rid


def _lock_tenant_runs(s: Session, tenant_id: uuid.UUID) -> None:
    s.execute(text("select pg_advisory_xact_lock(hashtext('match_runs:' || :t))"), {"t": str(tenant_id)})


def is_current_for_scope(s: Session, run: MatchRun, invoice_ids: list[str]) -> bool:
    """True when every invoice line in scope has its current result from ``run``."""
    line_ids = s.scalars(
        select(InvoiceLineRow.id).where(InvoiceLineRow.invoice_id.in_([uuid.UUID(i) for i in invoice_ids]))
    ).all()
    if not line_ids:
        return run.state == "succeeded"
    current = s.execute(
        select(LineMatch.invoice_line_id, LineMatch.match_run_id).where(
            LineMatch.invoice_line_id.in_(line_ids), LineMatch.is_current.is_(True)
        )
    ).all()
    return len(current) == len(line_ids) and all(r[1] == run.id for r in current)


def request_run(
    s: Session,
    tenant_id: uuid.UUID,
    invoice_ids: list[uuid.UUID],
    trigger: str = "manual",
    trigger_ref: uuid.UUID | None = None,
    ruleset_code: str = "v1",
    currency: str = "CAD",
) -> tuple[MatchRun, bool]:
    """Create a queued run and enqueue its job in the same transaction. Returns (run, created).

    No lock is taken here, so a request never waits for a running evaluation; a race can at
    worst create one extra run, which re-reads the inputs when it executes.
    """
    inp = build_match_input(s, invoice_ids, currency, ruleset_code)
    scope_ids = sorted(inp.test_document_ids | {str(i) for i in invoice_ids})
    fp = input_fingerprint(inp)
    candidates = s.scalars(
        select(MatchRun).where(MatchRun.input_fingerprint == fp).order_by(MatchRun.created_at.desc())
    ).all()
    for found in candidates:
        if sorted(found.scope.get("invoice_ids", [])) != scope_ids:
            continue
        if found.state in PENDING:
            return found, False  # same inputs already queued: idempotent
        if found.state == "succeeded" and is_current_for_scope(s, found, scope_ids):
            return found, False
    corr = get_correlation_id() or new_correlation_id()
    run = MatchRun(
        tenant_id=tenant_id,
        trigger=trigger,
        trigger_ref=trigger_ref,
        scope={"invoice_ids": scope_ids},
        input_fingerprint=fp,
        ruleset_version_id=_ruleset_id(s, ruleset_code),
        state="queued",
        correlation_id=uuid.UUID(corr),
    )
    s.add(run)
    s.flush()
    enqueue(s, TASK, tenant_id, {"match_run_id": str(run.id)}, corr)
    return run, True


def execute_run(s: Session, payload: dict[str, Any], ruleset_code: str = "v1", currency: str = "CAD") -> None:
    """Worker handler for ``match_run`` jobs. Runs inside the job wrapper's tenant session."""
    tenant_id = uuid.UUID(payload["tenant_id"])
    _lock_tenant_runs(s, tenant_id)
    run = s.get(MatchRun, uuid.UUID(payload["match_run_id"]))
    if run is None:
        raise PermanentJobError("match run not found in this tenant")
    if run.state not in PENDING:
        log.info("match_run_already_finished", extra={"match_run_id": str(run.id), "state": run.state})
        return
    if run.state != "running":
        if not transition(
            s, "match_runs", run.id, run.state_version, "running", started_at=datetime.now(UTC)
        ):
            return
        s.refresh(run)
    inp = build_match_input(s, [uuid.UUID(i) for i in run.scope["invoice_ids"]], currency, ruleset_code)
    fp = input_fingerprint(inp)
    if fp != run.input_fingerprint:
        other = s.scalar(
            select(MatchRun.id).where(
                MatchRun.input_fingerprint == fp, MatchRun.id != run.id, MatchRun.state.in_(PENDING)
            )
        )
        if other is not None:
            # Another pending run already covers exactly these inputs; it will store them.
            transition(s, "match_runs", run.id, run.state_version, "failed", finished_at=datetime.now(UTC))
            log.info("match_run_inputs_pending_elsewhere", extra={"match_run_id": str(run.id)})
            return
        run.input_fingerprint = fp  # record the inputs actually evaluated
    result = evaluate(inp)
    store_result(s, tenant_id, run, result)
    s.flush()
    s.refresh(run)
    transition(s, "match_runs", run.id, run.state_version, "succeeded")
