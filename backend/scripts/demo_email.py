"""``make demo-email`` (B7, T-3.3.4): post two synthetic, signed emails to the local intake webhook.

1. From ``billing@fictional-fasteners.example`` (an allowed sender in the demo): its invoice PDF goes
   straight into a new intake batch.
2. From ``accounts@unknown-supplier.example`` (not allowed): held for a person on Intake.

The messages are signed exactly as a provider would sign them (HMAC-SHA256 over
``<timestamp>.<body>``, ``intake.sign``) with the server's inbound key, and posted over HTTP to the
running API, so the real route checks the signature. Invented content only. Refuses in production.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
import uuid

from sqlalchemy import select

from matchdesk.core import load_settings, text_pdf
from matchdesk.identity import Tenant
from matchdesk.intake import sign, signing_key
from matchdesk.tenancy import get_engine, global_session

TENANT = "Demo Distributor Ltd (synthetic)"


def pdf(number: str) -> bytes:
    return text_pdf(
        [
            "INVOICE",
            "Synthetic document generated for the MatchDesk demo. Not a real invoice.",
            "",
            "Vendor: Fictional Fasteners Ltd",
            f"Invoice No: {number}",
            "Invoice Date: 2026-11-03",
            "PO Number: 4390",
            "Currency: CAD",
            "",
            "WS-M8 Washer M8 100 EA 0.05 5.00",
            "",
            "Subtotal: 5.00",
            "Tax: 0.00",
            "Total: 5.00",
        ],
        title=f"Invoice {number}",
    )


def post(url: str, payload: dict, key: bytes) -> str:
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    req = urllib.request.Request(  # noqa: S310 (local API only)
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-MatchDesk-Timestamp": ts,
            "X-MatchDesk-Signature": sign(body, ts, key),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (local API only)
        return json.loads(r.read())["status"]


def main() -> int:
    settings = load_settings()
    if settings.env == "production":
        print("demo-email: refused, MATCHDESK_ENV is production", file=sys.stderr)
        return 1
    with global_session(get_engine(settings.database_url)) as s:
        local = s.scalar(select(Tenant.intake_address_local).where(Tenant.name == TENANT))
    if not local:
        print("demo-email: the demo company has no intake address; run make demo-reset", file=sys.stderr)
        return 1
    to = f"{local}@{settings.intake_domain}"
    url = (
        os.environ.get("MATCHDESK_API_URL", f"http://127.0.0.1:{settings.api_port}") + "/api/v1/inbound/email"
    )
    key = signing_key(settings)
    run = uuid.uuid4().hex[:6]
    number = f"FF-11{run[:2].upper()}"
    allowed = {
        "message_id": f"demo-{run}-1@fictional-fasteners.example",
        "from": "billing@fictional-fasteners.example",
        "to": to,
        "subject": f"Invoice {number} (synthetic)",
        "attachments": [
            {"filename": f"{number}.pdf", "content_base64": base64.b64encode(pdf(number)).decode()}
        ],
    }
    unknown = {
        "message_id": f"demo-{run}-2@unknown-supplier.example",
        "from": "accounts@unknown-supplier.example",
        "to": to,
        "subject": "Please pay this invoice (synthetic)",
        "attachments": [
            {"filename": "UNK-77.pdf", "content_base64": base64.b64encode(pdf(f"UNK-{run[:2]}")).decode()}
        ],
    }
    print(f"demo-email: to {to}")
    print(f"  from billing@fictional-fasteners.example ({number}.pdf): {post(url, allowed, key)}")
    print(f"  from accounts@unknown-supplier.example: {post(url, unknown, key)}")
    print("  open Intake in the web app: the first is in a new batch, the second is held for you")
    return 0


if __name__ == "__main__":
    sys.exit(main())
