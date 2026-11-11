"""B2 file storage through the S3 API against local MinIO (IT-03 subset; TRD 8.7; R-13; T-2.2.5).

Uses the bucket and credentials from the gitignored ``backend/.env`` (local test values). Every
object the test writes is deleted at the end.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from matchdesk import blobstore
from matchdesk.core import NotFoundError, load_settings

from .b2_helpers import BASE_URL
from .seed import make_tenant

pytestmark = pytest.mark.integration


@pytest.fixture
def s3(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MATCHDESK_BLOB_BACKEND", "s3")
    settings = load_settings()
    if not (settings.s3_access_key and settings.s3_bucket and settings.s3_endpoint_url):
        pytest.skip("S3 settings missing: set MATCHDESK_S3_* in backend/.env")
    store = blobstore.store(settings)
    if not store.ready():
        pytest.skip("MinIO not reachable or bucket missing")
    prefixes: list[str] = []
    yield settings, store, prefixes
    client = store.client  # type: ignore[attr-defined]
    for prefix in prefixes:
        listed = client.list_objects_v2(Bucket=settings.s3_bucket, Prefix=prefix).get("Contents") or []
        for obj in listed:
            client.delete_object(Bucket=settings.s3_bucket, Key=obj["Key"])
        assert not client.list_objects_v2(Bucket=settings.s3_bucket, Prefix=prefix).get("Contents")


def test_upload_and_download_for_one_tenant_refused_for_another(app_engine, s3):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from matchdesk.api.app import create_app

    settings, store, prefixes = s3
    a = make_tenant(app_engine, "B2 files A")
    b = make_tenant(app_engine, "B2 files B")
    prefixes += [f"t/{a.tenant_id}/", f"t/{b.tenant_id}/"]
    api = TestClient(create_app(), base_url=BASE_URL)
    assert api.get("/readyz").status_code == 200  # readiness includes the bucket

    pdf = b"%PDF-1.7\n% synthetic invoice for B2 " + uuid.uuid4().hex.encode() + b"\n%%EOF\n"
    batch = api.post("/api/v1/intake/batches", headers=a.headers)
    assert batch.status_code == 201, batch.text
    up = api.post(
        f"/api/v1/intake/batches/{batch.json()['id']}/files",
        files={"file": ("../../etc/passwd.pdf", pdf, "text/plain")},
        headers={**a.headers, "Idempotency-Key": "b2-upload-1"},
    )
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]
    assert up.json()["mime_type"] == "application/pdf"  # sniffed, the declared type is ignored

    # The object is in MinIO under the tenant, purpose and source; no user-supplied name in the key.
    objects = store.client.list_objects_v2(Bucket=settings.s3_bucket, Prefix=f"t/{a.tenant_id}/")["Contents"]  # type: ignore[attr-defined]
    keys = [o["Key"] for o in objects]
    assert len(keys) == 1
    key = keys[0]
    assert key.startswith(f"t/{a.tenant_id}/invoice/upload/") and key.endswith(".pdf")
    assert f"/{doc_id}/" in key and "passwd" not in key

    # Download through the authorised endpoint only.
    got = api.get(f"/api/v1/documents/{doc_id}/content", headers=a.headers)
    assert got.status_code == 200 and got.content == pdf
    assert got.headers["content-security-policy"] == "sandbox"
    assert got.headers["content-disposition"] == f'attachment; filename="document-{doc_id}.pdf"'
    # Another tenant: not found, the same as a missing document.
    assert api.get(f"/api/v1/documents/{doc_id}/content", headers=b.headers).status_code == 404
    assert api.get(f"/api/v1/documents/{uuid.uuid4()}/content", headers=b.headers).status_code == 404
    # Signed out: 401. A viewer of B cannot upload into A's batch either: 404.
    assert (
        TestClient(create_app(), base_url=BASE_URL).get(f"/api/v1/documents/{doc_id}/content").status_code
        == 401
    )
    cross = api.post(
        f"/api/v1/intake/batches/{batch.json()['id']}/files",
        files={"file": ("x.pdf", pdf + b" ", "application/pdf")},
        headers={**b.headers, "Idempotency-Key": "b2-upload-2"},
    )
    assert cross.status_code == 404
    # blobstore refuses A's key in B's context, for reading and for writing.
    with pytest.raises(NotFoundError):
        blobstore.get(b.tenant_id, key, settings=settings)
    with pytest.raises(blobstore.BlobKeyError):
        blobstore.put(b.tenant_id, key, b"overwrite", settings=settings)
    # No public URL: the bucket refuses an anonymous read.
    anonymous = httpx.get(f"{settings.s3_endpoint_url}/{settings.s3_bucket}/{key}", timeout=5)
    assert anonymous.status_code == 403
    # Unsupported content is refused before storage.
    bad = api.post(
        f"/api/v1/intake/batches/{batch.json()['id']}/files",
        files={"file": ("invoice.pdf", b"MZ not a pdf", "application/pdf")},
        headers={**a.headers, "Idempotency-Key": "b2-upload-3"},
    )
    assert bad.status_code == 415


def test_blobstore_put_get_delete_round_trip(s3):  # type: ignore[no-untyped-def]
    settings, _store, prefixes = s3
    tenant = uuid.uuid4()
    prefixes.append(f"t/{tenant}/")
    key = blobstore.build_key(tenant, "export", b"report", source="system", ext="csv")
    blobstore.put(tenant, key, b"report", content_type="text/csv", settings=settings)
    assert blobstore.get(tenant, key, settings=settings) == b"report"
    blobstore.delete(tenant, key, settings=settings)
    with pytest.raises(NotFoundError):
        blobstore.get(tenant, key, settings=settings)


# ------------------------------------------------------------------ request-body limit (report 10.6 open item 1)


def _doc_count(engine, tenant_id) -> int:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from matchdesk.tenancy import session

    with session(tenant_id, engine) as s:
        return int(s.execute(text("select count(*) from documents")).scalar() or 0)


def test_oversize_upload_is_refused_before_anything_is_spooled_or_stored(app_engine, s3, monkeypatch):  # type: ignore[no-untyped-def]
    import starlette.formparsers as fp
    from fastapi.testclient import TestClient

    from matchdesk.api.app import create_app
    from matchdesk.api.limits import MAX_UPLOAD_BODY_BYTES

    settings, store, prefixes = s3
    w = make_tenant(app_engine, "B2 oversize")
    prefixes.append(f"t/{w.tenant_id}/")
    spools: list[object] = []
    real_spool = fp.SpooledTemporaryFile

    def counting_spool(*args, **kwargs):  # type: ignore[no-untyped-def]
        f = real_spool(*args, **kwargs)
        spools.append(f)
        return f

    monkeypatch.setattr(fp, "SpooledTemporaryFile", counting_spool)
    api = TestClient(create_app(), base_url=BASE_URL)
    batch = api.post("/api/v1/intake/batches", headers=w.headers).json()["id"]
    url = f"/api/v1/intake/batches/{batch}/files"
    big = b"%PDF-1.7\n" + b"0" * (MAX_UPLOAD_BODY_BYTES + 1024)

    # 1. Content-Length above the limit: 413 before the application reads the body.
    r = api.post(
        url,
        files={"file": ("big.pdf", big, "application/pdf")},
        headers={**w.headers, "Idempotency-Key": "big-1"},
    )
    assert r.status_code == 413 and r.json()["title"] == "Request body too large"
    assert spools == []  # nothing spooled to memory or disk

    # 2. No Content-Length (chunked): refused as soon as the streamed count passes the limit.
    boundary = "b2boundary"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="big.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    sent = 0

    def chunks():  # type: ignore[no-untyped-def]
        nonlocal sent
        yield head
        piece = b"%PDF-1.7\n" + b"0" * (1024 * 1024)
        while sent <= MAX_UPLOAD_BODY_BYTES + 4 * len(piece):
            sent += len(piece)
            yield piece
        yield f"\r\n--{boundary}--\r\n".encode()

    r2 = api.post(
        url,
        content=chunks(),
        headers={
            **w.headers,
            "Idempotency-Key": "big-2",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    assert r2.status_code == 413
    # Spooled at most up to the limit, and every spool closed (Starlette deletes closed spools).
    assert all(getattr(f, "closed", True) for f in spools)

    # 3. Nothing reached the database or MinIO.
    assert _doc_count(app_engine, w.tenant_id) == 0
    assert not store.client.list_objects_v2(Bucket=settings.s3_bucket, Prefix=f"t/{w.tenant_id}/").get(
        "Contents"
    )  # type: ignore[attr-defined]

    # 4. A JSON body above 1 MiB is refused too; a normal upload still works.
    huge_json = api.post(
        "/api/v1/match-runs",
        content=b"[" + b"0," * 600_000 + b"0]",
        headers={**w.headers, "Content-Type": "application/json"},
    )
    assert huge_json.status_code == 413
    ok = api.post(
        url,
        files={"file": ("ok.pdf", b"%PDF-1.7\nsmall\n%%EOF\n", "application/pdf")},
        headers={**w.headers, "Idempotency-Key": "small-1"},
    )
    assert ok.status_code == 201
