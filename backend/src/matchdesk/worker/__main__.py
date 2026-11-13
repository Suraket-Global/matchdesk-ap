"""Worker loop: claim a job, run it through the tenant wrapper, repeat."""

from __future__ import annotations

import signal
import sys
import time
from datetime import UTC, datetime
from typing import Any

from matchdesk.core import configure_logging, get_logger, load_settings, mailer_from_settings
from matchdesk.exceptions import MATCH_REQUEST_TASK, MATCH_RUN_TASK, execute_run, handle_match_request
from matchdesk.extraction import extractor_from_settings
from matchdesk.intake import PROCESS_DOCUMENT_TASK, make_handler, purge_raw
from matchdesk.qbo import SYNC_TASK, make_sync_handler, reader_for_tenant
from matchdesk.receiving import purge_drafts_everywhere
from matchdesk.reporting import (
    ARCHIVE_TASK,
    due_weekly,
    execute_due_deletions,
    expire_archives,
    make_archive_handler,
    run_operations,
)
from matchdesk.schema_registry import load_all_models
from matchdesk.tenancy import claim, get_engine, run_claimed

log = get_logger("matchdesk.worker")

# Every ORM model must be registered before the first flush: a standalone worker that never imported
# the identity models could not resolve the tenants foreign key of extraction_runs and left uploaded
# documents stuck in "running" (found in B4 when files were uploaded through the web app).
load_all_models()


def handlers(engine: Any) -> dict[str, Any]:
    # Extraction: MATCHDESK_EXTRACTOR selects the fake (tests), the local text-PDF reader, or a hosted
    # provider (deferred: no account). QuickBooks: per tenant (B11), recorded synthetic responses or
    # the Intuit client over the tenant's connection (tenants.qbo_mode, else MATCHDESK_QBO_MODE).
    settings = load_settings()
    return {
        MATCH_RUN_TASK: execute_run,
        MATCH_REQUEST_TASK: handle_match_request,
        PROCESS_DOCUMENT_TASK: make_handler(engine, extractor_from_settings(settings)),
        SYNC_TASK: make_sync_handler(
            engine, lambda tid: reader_for_tenant(engine, settings, tid), settings.qbo_page_size
        ),
        ARCHIVE_TASK: make_archive_handler(),
    }


def run_once(engine: Any = None) -> str | None:
    eng = engine or get_engine()
    job = claim(load_settings().job_lease_seconds, eng)
    if job is None:
        return None
    return run_claimed(job, handlers(eng), eng)


SCHEDULE_EVERY_SECONDS = 60


def scheduled(engine: Any, settings: Any, now: datetime | None = None) -> dict[str, int | None]:
    """Time-driven work: the Monday weekly summary (T-5.1.4) and the 7-day deletion of raw inbound
    email (schema.md 8; B7); since B9 the 7-day removal of receiving drafts never committed, the
    24-hour expiry of archive exports and the account deletions that are due. Each is idempotent, so
    a restart or a second worker repeats nothing. B10 (outside QA item 8): each runs with its own
    error handling and records its last success, so one failure never blocks the others."""
    at = now or datetime.now(UTC)
    done = run_operations(
        engine,
        [
            ("weekly_summary", lambda: due_weekly(engine, at, mailer_from_settings(settings), settings)),
            ("raw_email_cleanup", lambda: purge_raw(engine, settings, at)),
            ("receiving_draft_cleanup", lambda: purge_drafts_everywhere(engine, at)),
            ("archive_expiry", lambda: expire_archives(engine, at)),
            ("due_deletions", lambda: len(execute_due_deletions(engine))),
        ],
        at,
    )
    if any(done.values()) or None in done.values():
        log.info("scheduled", extra={k: v for k, v in done.items()})
    return done


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    log.info("worker_start", extra={"settings_hash": settings.fingerprint(), "service": "worker"})
    stop = {"flag": False}

    def _stop(*_a: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    engine = get_engine(settings.database_url)
    once = "--once" in sys.argv
    next_schedule = time.monotonic() - 1
    while not stop["flag"]:
        if time.monotonic() >= next_schedule:
            scheduled(engine, settings)
            next_schedule = time.monotonic() + SCHEDULE_EVERY_SECONDS
        state = run_once(engine)
        if once and state is None:
            break
        if state is None:
            time.sleep(1)
    log.info("worker_stop", extra={"service": "worker"})


if __name__ == "__main__":
    main()
