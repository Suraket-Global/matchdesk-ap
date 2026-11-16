"""B14 (2026-11-17): what the independent acceptance test could not reach, where no automated test
existed. PNG and JPEG invoices through the API with the local reader. (XLSX receiving files and
voiding an import: test_b3_receiving.py; alias create and retire, reopening: test_b3_workflow.py;
the idle limit on the server: test_b2_sign_in.py; the same in the browser: web/e2e/uncovered-b14.spec.ts
and web/src/b14-coverage.test.tsx.) Synthetic data."""

from __future__ import annotations

import struct
import uuid
import zlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from matchdesk.api.app import create_app
from matchdesk.extraction.local_pdf import LocalPdfExtractor
from matchdesk.intake import process_document
from matchdesk.intake.models import DocumentRow, InvoiceRow
from matchdesk.tenancy import session

from .b14_helpers import drain, out_of_date, pending_jobs
from .seed import make_tenant

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app())


def png(seed: int = 0) -> bytes:
    """A real 1 x 1 PNG (synthetic; ``seed`` changes the pixel so two files differ)."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    head = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixel = zlib.compress(b"\x00" + bytes([seed % 256, 0, 0]))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")


JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")  # start and end markers only


def test_png_and_jpeg_invoices_are_accepted_by_content_and_end_in_a_stated_state(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B14-IMG")
    batch = client.post("/api/v1/intake/batches", headers=w.headers).json()["id"]

    def up(name: str, data: bytes, declared: str, key: str):  # type: ignore[no-untyped-def]
        return client.post(
            f"/api/v1/intake/batches/{batch}/files",
            files={"file": (name, data, declared)},
            headers={**w.headers, "Idempotency-Key": key},
        )

    a = up("scan.png", png(1), "image/png", "img-1")
    b = up("photo.jpg", JPEG, "image/jpeg", "img-2")
    # The type comes from the bytes: a PNG named .pdf and declared a PDF is stored as a PNG.
    c = up("misnamed.pdf", png(2), "application/pdf", "img-3")
    assert [r.status_code for r in (a, b, c)] == [201, 201, 201], (a.text, b.text, c.text)
    assert [r.json()["mime_type"] for r in (a, b, c)] == ["image/png", "image/jpeg", "image/png"]
    # The same image again is one document, not two.
    again = up("scan-copy.png", png(1), "image/png", "img-4")
    assert again.status_code == 201 and again.json()["state"] == "duplicate_file"
    # The local reader reads text PDFs only (a hosted reader is deferred): it reads nothing from an
    # image with certainty, so the document waits for a person, who keys it on S-07. It is never
    # ready, never matched and never silently dropped.
    for r in (a, b, c):
        assert (
            process_document(app_engine, w.tenant_id, uuid.UUID(r.json()["id"]), LocalPdfExtractor())
            == "needs_review"
        )
    drain(app_engine)
    body = client.get(f"/api/v1/intake/batches/{batch}", headers=w.headers).json()
    t = body["totals"]
    assert (
        t["file_count"],
        t["needs review"],
        t["duplicate file"],
        t["ready"],
        t["failed"],
        t["refused"],
    ) == (4, 3, 1, 0, 0, 0)
    waiting = [f for f in body["files"] if f["displayed_state"] == "needs review"]
    assert {f["original_name"] for f in waiting} == {"scan.png", "photo.jpg", "misnamed.pdf"}
    with session(w.tenant_id, app_engine) as s:
        rows = s.scalars(select(InvoiceRow)).all()
        assert len(rows) == 3 and {r.verification_status for r in rows} == {"failed"}
        assert all(
            r.total is None and r.doc_number is None and r.vendor_id is None for r in rows
        )  # nothing invented
        assert s.scalar(select(DocumentRow.id).where(DocumentRow.state == "succeeded")) is None
        inv_id = rows[0].id
    review = client.get(f"/api/v1/invoices/{inv_id}", headers=w.headers).json()
    assert review["review"]["document_state"] == "needs_review" and review["lines"] == []
    assert not any(ln.get("status") == "matched" for ln in review["lines"])
    # Each is in the queue as "extraction not confirmed", and nothing is left out of date.
    q = client.get("/api/v1/exceptions", params={"status": "open"}, headers=w.headers).json()
    assert [i["type"] for i in q["items"]] == ["extraction_unverified"] * 3
    assert pending_jobs(app_engine, w) == 0 and out_of_date(app_engine, w) == []
    # The stored image is served back as what it is, to the account only.
    got = client.get(f"/api/v1/documents/{a.json()['id']}/content", headers=w.headers)
    assert (
        got.status_code == 200
        and got.headers["content-type"].startswith("image/png")
        and got.content == png(1)
    )
    other = make_tenant(app_engine, "Fictional Distributor B14-IMGx")
    assert client.get(f"/api/v1/documents/{a.json()['id']}/content", headers=other.headers).status_code == 404
