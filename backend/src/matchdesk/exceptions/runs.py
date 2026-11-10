"""Match runs: scope, fingerprint, job, supersede (T-4.1.6; TRD 6.3).

A run is unique on its input fingerprint, so requesting a run on unchanged
inputs returns the earlier run instead of evaluating again. The worker re-reads
the inputs; if they changed after the request, the run records the fingerprint
it actually evaluated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from matchdesk.core import get_correlation_id, get_logger, new_correlation_id
from matchdesk.exceptions.inputs import build_match_input
from matchdesk.exceptions.models import MatchRun, RulesetVersion
from matchdesk.exceptions.store import store_result
from matchdesk.matching import evaluate, input_fingerprint
from matchdesk.tenancy import PermanentJobError, enqueue, transition

log = get_logger("matchdesk.match_runs")
TASK = "match_run"


def _ruleset_id(s: Session, code: str) -> uuid.UUID:
    rid = s.scalar(select(RulesetVersion.id).where(RulesetVersion.code == code))
    if rid is None:
        raise PermanentJobError(f"rule set {code} missing")
    return rid


def request_run(
    s: Session,
    tenant_id: uuid.UUID,
    invoice_ids: list[uuid.UUID],
    trigger: str = "manual",
    trigger_ref: uuid.UUID | None = None,
    ruleset_code: str = "v1",
    currency: str = "CAD",
) -> tuple[MatchRun, bool]:
    """Create a queued run and enqueue its job in the same transaction. Returns (run, created)."""
    inp = build_match_input(s, invoice_ids, currency, ruleset_code)
    scope_ids = sorted(inp.test_document_ids)
    fp = input_fingerprint(inp)
    found = s.scalar(select(MatchRun).where(MatchRun.input_fingerprint == fp))
    if found is not None:
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
    run = s.get(MatchRun, uuid.UUID(payload["match_run_id"]))
    if run is None:
        raise PermanentJobError("match run not found in this tenant")
    if run.state not in ("queued", "retry_wait", "running"):
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
        clash = s.scalar(select(MatchRun.id).where(MatchRun.input_fingerprint == fp, MatchRun.id != run.id))
        if clash is not None:
            transition(s, "match_runs", run.id, run.state_version, "failed", finished_at=datetime.now(UTC))
            log.info("match_run_inputs_already_evaluated", extra={"match_run_id": str(run.id)})
            return
        run.input_fingerprint = fp
    result = evaluate(inp)
    store_result(s, tenant_id, run, result)
    s.flush()
    s.refresh(run)
    transition(s, "match_runs", run.id, run.state_version, "succeeded")
