"""Request-body limits and the client address (wiring only; B2 security review round 1, items left open).

Body limit: a pure ASGI middleware that refuses a request with 413 when ``Content-Length`` exceeds
the limit for its path, before the application reads a byte, and, for a body without a length
(chunked), as soon as the streamed byte count passes the limit. Uploads are therefore never spooled
beyond the limit, and nothing reaches the file store.

Client address: the direct TCP peer, unless the peer is a configured trusted proxy; then the
right-most ``X-Forwarded-For`` hop that is not itself a trusted proxy. Uvicorn's own proxy-header
handling is switched off (see ``api.app.uvicorn_options``), so this is the only place that decides.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

# TRD 8.7: 20 MB per file for every accepted type (PDF, PNG, JPEG).
MAX_FILE_BYTES: dict[str, int] = {
    "application/pdf": 20 * 1024 * 1024,
    "image/png": 20 * 1024 * 1024,
    "image/jpeg": 20 * 1024 * 1024,
}
MAX_UPLOAD_FILE_BYTES = max(MAX_FILE_BYTES.values())
MULTIPART_OVERHEAD_BYTES = 64 * 1024  # boundaries and part headers
MAX_UPLOAD_BODY_BYTES = MAX_UPLOAD_FILE_BYTES + MULTIPART_OVERHEAD_BYTES
MAX_JSON_BODY_BYTES = 1024 * 1024  # every other request: JSON of a few kilobytes at most

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def body_limit_for(path: str) -> int:
    if path.startswith("/api/v1/intake/batches/") and path.endswith("/files"):
        return MAX_UPLOAD_BODY_BYTES
    return MAX_JSON_BODY_BYTES


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = body_limit_for(scope.get("path", ""))
        length = _content_length(scope)
        if length is not None and length > limit:
            await _send_413(send)  # nothing read, nothing spooled
            return
        seen = 0
        exceeded = False
        started = False

        async def limited_receive() -> Message:
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    exceeded = True
                    raise _TooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if exceeded:
                return  # whatever the application answers, the client gets the 413 below
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _TooLarge:
            pass
        except Exception:
            if not exceeded:
                raise
        if exceeded and not started:
            await _send_413(send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _send_413(send: Send) -> None:
    body = json.dumps(
        {
            "type": "about:blank",
            "title": "Request body too large",
            "status": 413,
            "detail": "Request body too large",
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _networks(trusted: Iterable[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(t, strict=False) for t in trusted]


def _parse(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def client_address(peer: str | None, forwarded_for: list[str], trusted: Iterable[str]) -> str | None:
    """The address the rate limits use. ``forwarded_for`` holds every X-Forwarded-For header value."""
    peer_ip = _parse(peer) if peer else None
    if peer_ip is None:
        return None
    nets = _networks(trusted)

    def is_trusted(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return any(ip.version == n.version and ip in n for n in nets)

    if not is_trusted(peer_ip):
        return str(peer_ip)  # a client cannot choose its address by sending the header
    hops = [h for value in forwarded_for for h in value.split(",")]
    for hop in reversed(hops):
        ip = _parse(hop)
        if ip is None:
            return str(peer_ip)  # a malformed hop: stop and count the proxy itself
        if not is_trusted(ip):
            return str(ip)
    return str(peer_ip)
