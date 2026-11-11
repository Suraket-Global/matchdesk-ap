"""File keys and tenant-checked file access (TRD 8.2, 8.7; R-13; T-2.2.5 (a) subset; B2).

Key format (TRD 8.7): ``t/{tenant_id}/{purpose}/{source}/{yyyy}/{mm}/{record_id}/{sha256}.{ext}``.
``put``, ``get`` and ``delete`` take the current tenant and refuse any key
outside it, so a caller cannot reach another tenant's file even with a valid
key (IT-03). No path or name supplied by a user is ever part of a key.

Two stores behind one interface, selected by ``MATCHDESK_BLOB_BACKEND``:
``local`` (a directory) and ``s3`` (the S3 API: MinIO locally, a provider later).
Objects are private; nothing here creates a public or presigned URL. Files reach
a browser only through the authorised download endpoint.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from matchdesk.core import NotFoundError, Settings, TenantContextError, load_settings

PURPOSES = frozenset({"invoice", "receiving", "export", "inbound_raw"})
SOURCES = frozenset({"upload", "email", "system"})
_EXT = re.compile(r"^[a-z0-9]{1,8}$")


class BlobKeyError(TenantContextError):
    """A key outside the current tenant, or malformed."""


class BlobStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes | None: ...
    def delete(self, key: str) -> None: ...
    def ready(self) -> bool: ...


def build_key(
    tenant_id: uuid.UUID | str,
    purpose: str,
    data: bytes,
    *,
    source: str = "upload",
    record_id: uuid.UUID | str | None = None,
    ext: str = "bin",
    when: datetime | None = None,
) -> str:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose}")
    if source not in SOURCES:
        raise ValueError(f"unknown source {source}")
    if not _EXT.match(ext):
        raise ValueError("extension must be 1-8 lowercase letters or digits")
    at = when or datetime.now(UTC)
    rid = uuid.UUID(str(record_id)) if record_id is not None else uuid.uuid4()
    digest = hashlib.sha256(data).hexdigest()
    return f"t/{uuid.UUID(str(tenant_id))}/{purpose}/{source}/{at:%Y}/{at:%m}/{rid}/{digest}.{ext}"


def _check(tenant_id: uuid.UUID | str, key: str) -> None:
    prefix = f"t/{uuid.UUID(str(tenant_id))}/"
    parts = key.split("/")
    if not key.startswith(prefix) or ".." in parts or "" in parts or "\\" in key:
        raise BlobKeyError("key is outside the current tenant")


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, key: str) -> bytes | None:
        path = self.root / key
        return path.read_bytes() if path.is_file() else None

    def delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok=True)

    def ready(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".ready"
            probe.write_bytes(b"1")
            probe.unlink()
        except OSError:
            return False
        return True


class S3Store:
    """Private bucket over the S3 API. Credentials come from settings only."""

    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.s3_bucket
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            ),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                return None
            raise
        return bytes(obj["Body"].read())

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def ready(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            return False
        return True


@lru_cache(maxsize=8)
def _store_for(settings: Settings) -> BlobStore:
    if settings.blob_backend == "s3":
        return S3Store(settings)
    if settings.blob_backend == "local":
        return LocalStore(settings.blob_root)
    raise ValueError(f"unknown blob backend {settings.blob_backend}")


def store(settings: Settings | None = None, root: Path | None = None) -> BlobStore:
    """The configured store. ``root`` forces a local directory (tests, B1 callers)."""
    if root is not None:
        return LocalStore(root)
    return _store_for(settings or load_settings())


def put(
    tenant_id: uuid.UUID | str,
    key: str,
    data: bytes,
    root: Path | None = None,
    content_type: str = "application/octet-stream",
    settings: Settings | None = None,
) -> None:
    _check(tenant_id, key)
    store(settings, root).put(key, data, content_type)


def get(
    tenant_id: uuid.UUID | str, key: str, root: Path | None = None, settings: Settings | None = None
) -> bytes:
    try:
        _check(tenant_id, key)
    except BlobKeyError as exc:
        raise NotFoundError("file not found") from exc
    data = store(settings, root).get(key)
    if data is None:
        raise NotFoundError("file not found")
    return data


def delete(
    tenant_id: uuid.UUID | str, key: str, root: Path | None = None, settings: Settings | None = None
) -> None:
    _check(tenant_id, key)
    store(settings, root).delete(key)


__all__ = [
    "BlobKeyError",
    "BlobStore",
    "LocalStore",
    "S3Store",
    "build_key",
    "delete",
    "get",
    "put",
    "store",
]
