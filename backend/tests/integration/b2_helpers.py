"""Helpers for the B2 integration tests: the local Mailpit inbox and per-test clients.

Mailpit (http://127.0.0.1:8025) is shared by every repository on this machine, so tests use
unique synthetic addresses, read only their own messages and delete only those.
"""

from __future__ import annotations

import random
import re
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from matchdesk.api.app import create_app

MAILPIT = "http://127.0.0.1:8025/api/v1"
BASE_URL = "https://app.matchdesk.test"


def mailpit_up() -> bool:
    try:
        return httpx.get(f"{MAILPIT}/messages?limit=1", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


needs_mailpit = pytest.mark.skipif(not mailpit_up(), reason="Mailpit is not running on 127.0.0.1:8025")


def client() -> TestClient:
    """A separate 'browser' with its own cookie jar and its own synthetic IP address."""
    ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
    return TestClient(create_app(), base_url=BASE_URL, client=(ip, 50000))


def messages_to(address: str) -> list[dict[str, Any]]:
    r = httpx.get(f"{MAILPIT}/search", params={"query": f'to:"{address}"', "limit": 50}, timeout=5)
    r.raise_for_status()
    return list(r.json().get("messages") or [])


def wait_for_messages(address: str, count: int = 1, timeout: int = 5) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while True:
        found = messages_to(address)
        if len(found) >= count or time.monotonic() > deadline:
            return found
        time.sleep(0.1)


def message_text(message_id: str) -> str:
    r = httpx.get(f"{MAILPIT}/message/{message_id}", timeout=5)
    r.raise_for_status()
    return str(r.json()["Text"])


def token_from(text: str, path: str = "/login/verify") -> str:
    m = re.search(re.escape(path) + r"#t=([A-Za-z0-9_\-]+)", text)
    assert m, "no link in the message"
    return m.group(1)


def latest_token(address: str, path: str = "/login/verify", count: int = 1) -> str:
    found = wait_for_messages(address, count)
    assert len(found) >= count, f"expected {count} message(s), found {len(found)}"
    newest = max(found, key=lambda m: m["Created"])
    return token_from(message_text(newest["ID"]), path)


def delete_messages_to(*addresses: str) -> None:
    ids = [m["ID"] for a in addresses for m in messages_to(a)]
    if ids:
        httpx.request("DELETE", f"{MAILPIT}/messages", json={"IDs": ids}, timeout=5)
