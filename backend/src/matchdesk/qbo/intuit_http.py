"""GET-only HTTP client for the QuickBooks Online Accounting API (B11; T-1.1.1, T-3.1.2).

Read only by construction: the one request method sends ``GET`` with no body. There is no way to
send a POST, PUT or DELETE to a QuickBooks data endpoint through this module (the only POSTs in the
product are the OAuth token exchange, refresh and revoke in ``oauth.py``).

Two reads exist, both from Intuit's public Accounting API reference: the query endpoint
``GET /v3/company/{realmId}/query?query=<statement>`` and ``GET /v3/company/{realmId}/companyinfo/
{realmId}``. A statement must start with ``select``. A 401 asks the token source once for a fresh
token (``rejected`` names the refused one, so a single refresher per connection does the work) and
retries once. 429, 5xx and network errors raise ``QboTransientError``; the sync retries and resumes
from its cursor. Other answers (for example a 400 for a bad statement) are returned to the caller.

Headers that bear on call limits are kept (``limit_headers``) so T-1.1.1 can record them. The
access token, the realm ID and Intuit's request ID (``intuit_tid``) are never logged.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from matchdesk.core import Settings
from matchdesk.qbo.client import QboTransientError

TokenSource = Callable[[str | None], str]


@dataclass(frozen=True)
class HttpAnswer:
    status: int
    headers: dict[str, str]
    body: bytes


Transport = Callable[[str, dict[str, str], int], HttpAnswer]


def urllib_get(url: str, headers: dict[str, str], timeout: int) -> HttpAnswer:
    """The default transport: one GET over HTTPS. HTTP error statuses are answers, not raises."""
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310 (https from settings)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return HttpAnswer(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read())
    except urllib.error.HTTPError as exc:
        return HttpAnswer(exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read() or b"")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise QboTransientError("QuickBooks not reachable") from None


class QboAuthError(RuntimeError):
    """QuickBooks refused a freshly refreshed token too (401 twice): the connection is unusable."""


@dataclass(frozen=True)
class ApiAnswer:
    """One read: what was asked (path and statement, never the token) and what came back."""

    path: str
    statement: str | None
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        """The body parsed with ``Decimal`` for every number (no binary floats)."""
        return json.loads(self.body or b"{}", parse_float=Decimal, parse_int=Decimal)


LIMIT_HEADER_WORDS = ("rate", "limit", "retry", "throttl", "quota")


def limit_headers(headers: dict[str, str]) -> dict[str, str]:
    """Response headers that bear on call limits, plus ``date`` and ``content-type``."""
    return {
        k: v
        for k, v in headers.items()
        if k in ("date", "content-type") or any(w in k for w in LIMIT_HEADER_WORDS)
    }


class IntuitApi:
    """Read-only Accounting API client for one realm, with a token source from ``oauth``."""

    def __init__(
        self,
        settings: Settings,
        realm_id: str,
        tokens: TokenSource,
        transport: Transport = urllib_get,
        timeout: int = 30,
    ) -> None:
        self.base = settings.qbo_api_base_url.rstrip("/")
        self.minor_version = settings.qbo_minor_version
        self.realm_id = realm_id
        self._tokens = tokens
        self._transport = transport
        self._timeout = timeout

    def query(self, statement: str) -> ApiAnswer:
        if not statement.lstrip().lower().startswith("select "):
            raise ValueError("only select statements are sent to the query endpoint")
        return self._get("query", {"query": statement}, statement)

    def company_info(self) -> ApiAnswer:
        return self._get(f"companyinfo/{urllib.parse.quote(self.realm_id, safe='')}", {}, None)

    def _get(self, tail: str, params: dict[str, str], statement: str | None) -> ApiAnswer:
        realm = urllib.parse.quote(self.realm_id, safe="")
        query = urllib.parse.urlencode({**params, "minorversion": self.minor_version})
        url = f"{self.base}/v3/company/{realm}/{tail}?{query}"
        token = self._tokens(None)
        answer = self._transport(url, _headers(token), self._timeout)
        if answer.status == 401:
            token = self._tokens(token)
            answer = self._transport(url, _headers(token), self._timeout)
            if answer.status == 401:
                raise QboAuthError("QuickBooks refused the refreshed access token")
        if answer.status == 429 or answer.status >= 500:
            raise QboTransientError(f"QuickBooks HTTP {answer.status}")
        path = "/v3/company/{realmId}/" + tail.replace(self.realm_id, "{realmId}")
        return ApiAnswer(path, statement, answer.status, answer.headers, answer.body)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}
