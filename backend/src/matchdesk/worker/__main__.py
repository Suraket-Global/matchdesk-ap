"""Worker loop: claim a job, run it through the tenant wrapper, repeat."""

from __future__ import annotations

import signal
import sys
import time
from typing import Any

from matchdesk.core import configure_logging, get_logger, load_settings
from matchdesk.exceptions import MATCH_RUN_TASK, execute_run
from matchdesk.extraction import FakeExtractor
from matchdesk.intake import PROCESS_DOCUMENT_TASK, make_handler
from matchdesk.tenancy import claim, get_engine, run_claimed

log = get_logger("matchdesk.worker")


def handlers(engine: Any) -> dict[str, Any]:
    # B1: the extraction provider is the fake; no real provider is configured (no account, no key).
    return {MATCH_RUN_TASK: execute_run, PROCESS_DOCUMENT_TASK: make_handler(engine, FakeExtractor())}


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
