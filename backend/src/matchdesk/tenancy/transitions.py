"""The shared state-transition helper (TRD 6.3, R-01, R-02).

Every transition is ``UPDATE ... SET state = :new, state_version = state_version + 1
WHERE id = :id AND state_version = :seen``. A stale or repeated event updates zero
rows; it is logged and dropped, so a newer state is never overwritten by an older event.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from matchdesk.core import get_logger

log = get_logger("matchdesk.transitions")

# Tables with a state machine, and the states each may take.
STATE_TABLES: dict[str, frozenset[str]] = {
    "documents": frozenset(
        {"queued", "running", "succeeded", "needs_review", "retry_wait", "failed", "duplicate_file"}
    ),
    "match_runs": frozenset({"queued", "running", "succeeded", "retry_wait", "failed"}),
    "receiving_imports": frozenset({"draft", "queued", "running", "succeeded", "failed", "voided"}),
}
ALLOWED_EXTRA = frozenset(
    {
        "lease_expires_at",
        "attempts",
        "failure_code",
        "started_at",
        "finished_at",
        "lines_evaluated",
        "lines_matched",
        "exceptions_raised",
        "committed_at",
        "voided_at",
    }
)


def transition(
    s: Session,
    table: str,
    row_id: uuid.UUID | str,
    seen_version: int,
    new_state: str,
    **extra: Any,
) -> bool:
    """Compare-and-set a state. Returns False (and changes nothing) for a stale event."""
    if table not in STATE_TABLES:
        raise ValueError(f"no state machine on {table}")
    if new_state not in STATE_TABLES[table]:
        raise ValueError(f"{new_state} is not a state of {table}")
    unknown = set(extra) - ALLOWED_EXTRA
    if unknown:
        raise ValueError(f"unexpected columns: {sorted(unknown)}")
    sets = "".join(f", {k} = :{k}" for k in sorted(extra))
    sql = (
        f"update {table} set state = :new, state_version = state_version + 1{sets} "  # noqa: S608
        "where id = :id and state_version = :seen"
    )
    result = s.execute(text(sql), {"new": new_state, "id": str(row_id), "seen": seen_version, **extra})
    if result.rowcount != 1:  # type: ignore[attr-defined]
        log.info(
            "stale_transition_dropped",
            extra={"entity_type": table, "entity_id": str(row_id), "to_state": new_state},
        )
        return False
    return True
