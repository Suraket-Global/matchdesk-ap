"""Worker loop: claim a job, run it through the tenant wrapper, repeat."""

from __future__ import annotations

import signal
import sys
import time
from typing import Any

from matchdesk.core import configure_logging, get_logger, load_settings
from matchdesk.exceptions import MATCH_REQUEST_TASK, MATCH_RUN_TASK, execute_run, handle_match_request
from matchdesk.extraction import extractor_from_settings
from matchdesk.intake import PROCESS_DOCUMENT_TASK, make_handler
from matchdesk.qbo import SYNC_TASK, make_sync_handler, reader_from_settings
from matchdesk.tenancy import claim, get_engine, run_claimed

log = get_logger("matchdesk.worker")


def handlers(engine: Any) -> dict[str, Any]:
    # Extraction: MATCHDESK_EXTRACTOR selects the fake (tests), the local text-PDF reader, or a hosted
    # provider (deferred: no account). QuickBooks: recorded synthetic responses or the unconfigured
    # Intuit client (MATCHDESK_QBO_MODE).
    settings = load_settings()
    return {
        MATCH_RUN_TASK: execute_run,
        MATCH_REQUEST_TASK: handle_match_request,
        PROCESS_DOCUMENT_TASK: make_handler(engine, extractor_from_settings(settings)),
        SYNC_TASK: make_sync_handler(engine, lambda: reader_from_settings(settings), settings.qbo_page_size),
    }


def run_once(engine: Any = None) -> str | None:
    eng = engine or get_engine()
    job = claim(load_settings().job_lease_seconds, eng)
    if job is None:
        return None
    return run_claimed(job, handlers(eng), eng)


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
    while not stop["flag"]:
        state = run_once(engine)
        if once and state is None:
            break
        if state is None:
            time.sleep(1)
    log.info("worker_stop", extra={"service": "worker"})


if __name__ == "__main__":
    main()
