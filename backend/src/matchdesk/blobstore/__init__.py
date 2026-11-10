"""File keys and access on the local volume (TRD 8.2, 8.7; T-2.2.5 (a) subset).

Keys begin ``t/{tenant_id}/``. ``put`` and ``get`` take the current tenant and
refuse any key outside it, so a caller cannot reach another tenant's file even
with a valid key (IT-03). No path supplied by a user is ever used.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from matchdesk.core import NotFoundError, TenantContextError, load_settings

PURPOSES = frozenset({"invoice", "receiving", "export", "inbound_raw"})


class BlobKeyError(TenantContextError):
    """A key outside the current tenant, or malformed."""


def build_key(tenant_id: uuid.UUID | str, purpose: str, data: bytes) -> str:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose}")
    digest = hashlib.sha256(data).hexdigest()
    return f"t/{uuid.UUID(str(tenant_id))}/{purpose}/{digest[:2]}/{digest}"


def _check(tenant_id: uuid.UUID | str, key: str) -> None:
    prefix = f"t/{uuid.UUID(str(tenant_id))}/"
    if not key.startswith(prefix) or ".." in key.split("/") or "\\" in key:
        raise BlobKeyError("key is outside the current tenant")


def _path(root: Path, key: str) -> Path:
    return root / key


def put(tenant_id: uuid.UUID | str, key: str, data: bytes, root: Path | None = None) -> None:
    _check(tenant_id, key)
    path = _path(root or load_settings().blob_root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def get(tenant_id: uuid.UUID | str, key: str, root: Path | None = None) -> bytes:
    try:
        _check(tenant_id, key)
    except BlobKeyError as exc:
        raise NotFoundError("file not found") from exc
    path = _path(root or load_settings().blob_root, key)
    if not path.is_file():
        raise NotFoundError("file not found")
    return path.read_bytes()


__all__ = ["BlobKeyError", "build_key", "get", "put"]
