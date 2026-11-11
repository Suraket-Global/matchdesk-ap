"""Time-based one-time codes, RFC 6238 (SHA-1, 6 digits, 30-second steps) for operators (TRD 8.1).

The server clock decides the step (ASVS 6.5.8); one step either side is accepted for clock drift,
and a step is accepted at most once (ASVS 6.5.1).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1


def new_secret() -> bytes:
    return secrets.token_bytes(20)  # 160 bits, CSPRNG (ASVS 6.5.3)


def secret_b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode().rstrip("=")


def step_at(when: datetime) -> int:
    return int(when.timestamp()) // STEP_SECONDS


def code_at_step(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def verify(secret: bytes, code: str, when: datetime, last_step: int | None) -> int | None:
    """Return the matched step, or None. A step at or before ``last_step`` is refused."""
    if not (len(code) == DIGITS and code.isascii() and code.isdigit()):  # B2 review s15: ASCII only
        return None
    now = step_at(when)
    for step in range(now - DRIFT_STEPS, now + DRIFT_STEPS + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at_step(secret, step), code):
            return step
    return None


def provisioning_uri(secret: bytes, account: str, issuer: str = "MatchDesk") -> str:
    return f"otpauth://totp/{issuer}:{account}?secret={secret_b32(secret)}&issuer={issuer}&digits=6&period=30"
