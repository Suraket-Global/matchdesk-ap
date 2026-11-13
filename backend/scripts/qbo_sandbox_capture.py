"""T-1.1.1: read the Intuit sandbox company of the sandbox tenant and record every answer (B11).

Read only (GET through ``matchdesk.qbo.IntuitApi``; the only POST is Intuit's token refresh when the
access token is near expiry). Needs ``make seed-sandbox`` and a connection made by the controller on
S-04. Writes to ``backend/var/qbo-capture/<UTC time>/`` (gitignored):

- ``raw/``: each answer exactly as received, with every response header (stays on this machine);
- ``sanitised/``: the same answers with the realm ID, Intuit request IDs and e-mail addresses
  removed and headers cut to those bearing on call limits (``matchdesk.qbo.capture``);
- ``summary.json``: counts and shapes for the fact sheet (``docs/qbo-fact-sheet.md``, phase B).

Before anything is written to ``sanitised/`` every file is checked for the realm ID, the access and
refresh tokens, the app's client ID and secret, request IDs and e-mail addresses; one hit stops the
script before it writes (exit 3) and names only the kind of value. ``--fixtures DIR`` also copies
the sanitised answers there (for example ``backend/fixtures/qbo/sandbox``); nothing is copied
without that flag. Prints counts and paths only, never a token, the realm ID or a response body.
Refuses when ``MATCHDESK_ENV`` is ``production``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from matchdesk.core import load_settings
from matchdesk.identity import Tenant
from matchdesk.qbo import (
    IntuitApi,
    get_connection,
    stored_tokens,
    tenant_qbo_mode,
    token_endpoint_for,
    token_source,
)
from matchdesk.qbo.capture import capture_all, leaks, request_ids, sanitised_record, summarise, user_ids
from matchdesk.tenancy import get_engine, global_session, session

ROOT = Path(__file__).resolve().parents[1]
SANDBOX_TENANT = "Sandbox Distributor (Intuit sandbox)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--tenant", default=SANDBOX_TENANT, help="tenant name (default: the seeded sandbox tenant)"
    )
    ap.add_argument("--page-size", type=int, default=100, help="MAXRESULTS per query page (1 to 1000)")
    ap.add_argument("--out", default=None, help="output folder (default backend/var/qbo-capture/<time>)")
    ap.add_argument("--fixtures", default=None, help="also copy the sanitised answers to this folder")
    args = ap.parse_args()
    settings = load_settings()
    if settings.env.lower() in {"production", "prod"}:
        print("qbo-capture: refused, MATCHDESK_ENV is production", file=sys.stderr)
        return 1
    engine = get_engine(settings.database_url)
    with global_session(engine) as s:
        tenant = s.scalar(select(Tenant).where(Tenant.name == args.tenant))
        if tenant is None:
            print(f"qbo-capture: no tenant named '{args.tenant}' (run make seed-sandbox)", file=sys.stderr)
            return 1
        tid = tenant.id
    with session(tid, engine) as s:
        if tenant_qbo_mode(s, settings, tid) != "intuit":
            print("qbo-capture: this tenant is not in intuit mode", file=sys.stderr)
            return 1
        conn = get_connection(s)
        if conn is None or conn.status != "connected":
            print("qbo-capture: not connected; the controller connects on S-04 first", file=sys.stderr)
            return 1
        realm = conn.realm_id
    endpoint = token_endpoint_for(settings, "intuit")
    api = IntuitApi(settings, realm, token_source(engine, settings, endpoint, tid))
    cap = capture_all(api, args.page_size)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else ROOT / "var" / "qbo-capture" / stamp
    raw_dir, clean_dir = out / "raw", out / "sanitised"
    raw_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for n, a in enumerate(cap.answers, start=1):
        stem = "CompanyInfo" if a.statement is None else a.statement.split(" from ")[1].split(" ")[0]
        kind = "count" if a.statement and "count(*)" in a.statement else "page"
        name = f"{n:03d}-{stem}-{kind}.json"
        names.append(name)
        raw = {
            "request": {"method": "GET", "path": a.path, "query": a.statement},
            "status": a.status,
            "headers": a.headers,
            "body_text": a.body.decode("utf-8", "replace"),
        }
        (raw_dir / name).write_text(json.dumps(raw, indent=2))

    # The last gate before anything leaves the gitignored raw folder.
    with session(tid, engine) as s:
        tokens = stored_tokens(s, settings, tid)
    forbidden = {
        "realm ID": [realm],
        "token": tokens,
        "client ID": [settings.qbo_client_id],
        "client secret": [settings.qbo_client_secret],
        "request ID": sorted(request_ids(cap.answers)),
        "Intuit user ID": sorted(user_ids(cap.answers)),
    }
    cleaned = {name: sanitised_record(a, realm) for name, a in zip(names, cap.answers, strict=True)}
    summary = json.dumps(
        {"captured_at": stamp, "page_size": args.page_size, **summarise(cap.answers)}, indent=2
    )
    for name, text in [*cleaned.items(), ("summary.json", summary)]:
        found = leaks(text, forbidden)
        if found:
            print(f"qbo-capture: refused to write {name}: still contains {', '.join(found)}", file=sys.stderr)
            return 3
    clean_dir.mkdir(parents=True, exist_ok=True)
    for name, text in cleaned.items():
        (clean_dir / name).write_text(text)
    (out / "summary.json").write_text(summary)
    if args.fixtures:
        target = Path(args.fixtures)
        target.mkdir(parents=True, exist_ok=True)
        for name in cleaned:
            shutil.copyfile(clean_dir / name, target / name)
        shutil.copyfile(out / "summary.json", target / "summary.json")
    statuses = summarise(cap.answers)["statuses"]
    print(f"qbo-capture: {len(cap.answers)} reads, statuses {statuses}")
    print(f"  raw (stays local): {raw_dir}")
    print(f"  sanitised: {clean_dir}")
    print(f"  summary: {out / 'summary.json'}")
    if args.fixtures:
        print(f"  copied to: {args.fixtures}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
