"""AES-256-GCM sealing with a key identifier, so the key can be rotated (TRD 8.3; B2).

Sealed format: ``b"v1." + key_id + b"." + nonce(12) + ciphertext_and_tag``. Used for operator TOTP
seeds now and for QuickBooks refresh tokens later.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SealError(ValueError):
    """Wrong key, unknown key id, or a damaged value."""


def _key(key_b64: str) -> bytes:
    try:
        key = base64.b64decode(key_b64, validate=True)
    except ValueError as exc:
        raise SealError("token key is not base64") from exc
    if len(key) != 32:
        raise SealError("token key must be 32 bytes")
    return key


def seal(key_b64: str, key_id: str, plaintext: bytes, context: bytes) -> bytes:
    if not key_id.isalnum():
        raise SealError("key id must be alphanumeric")
    nonce = os.urandom(12)
    ct = AESGCM(_key(key_b64)).encrypt(nonce, plaintext, context)
    return b"v1." + key_id.encode() + b"." + nonce + ct


def unseal(keys: dict[str, str], sealed: bytes, context: bytes) -> bytes:
    try:
        version, key_id, rest = sealed.split(b".", 2)
    except ValueError as exc:
        raise SealError("damaged value") from exc
    if version != b"v1" or key_id.decode() not in keys:
        raise SealError("unknown key id")
    nonce, ct = rest[:12], rest[12:]
    try:
        return AESGCM(_key(keys[key_id.decode()])).decrypt(nonce, ct, context)
    except Exception as exc:
        raise SealError("cannot open value") from exc
