"""IT-05, IT-06, IT-07: stale events, late completions, batch states and retries."""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from sqlalchemy import text

from matchdesk.extraction import FakeExtractor
from matchdesk.intake import add_file, batch_summary, complete, create_batch, retry_failed, take
from matchdesk.intake.models import DocumentRow
from matchdesk.tenancy import session, transition
from matchdesk.worker.__main__ import run_once

from .seed import make_tenant

pytestmark = pytest.mark.integration


def fake_pdf(i: int, *, consistent: bool = True, encrypted: bool = False) -> bytes:
    if encrypted:
        return f"%FAKE-PDF-ENCRYPTED {i}".encode()
    total = "4.20" if consistent else "9.99"
    body = {
        "n": i,
        "lines": [{"qty": "1", "unit_price": "4.20", "amount": "4.20"}],
        "tax_total": "0",
        "total": total,
    }
    return b"%FAKE-PDF\n" + json.dumps(body).encode()


def test_it05_stale_and_repeated_events_change_nothing(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "IT-05 tenant")
    with session(w.tenant_id, app_engine) as s:
        batch = create_batch(s, w.tenant_id)
        doc = add_file(s, w.tenant_id, w.user_id, batch.id, "k", fake_pdf(1))
        s.execute(
            text("update documents set state = 'succeeded', state_version = 4 where id = :d"),
            {"d": str(doc.id)},
        )
    with session(w.tenant_id, app_engine) as s:
        assert transition(s, "documents", doc.id, 2, "running") is False
        assert transition(s, "documents", doc.id, 4, "succeeded") is True  # first delivery
        assert transition(s, "documents", doc.id, 4, "succeeded") is False  # repeated delivery
        row = s.get(DocumentRow, doc.id)
        assert (row.state, row.state_version) == ("succeeded", 5)


def test_it06_late_completion_after_lease_expired(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "IT-06 tenant")
    data = fake_pdf(7)
    with session(w.tenant_id, app_engine) as s:
        batch = create_batch(s, w.tenant_id)
        doc = add_file(s, w.tenant_id, w.user_id, batch.id, "k", data)
    sha = hashlib.sha256(data).digest()
    first = take(app_engine, w.tenant_id, doc.id)
    assert first is not None
    # The first worker's lease expires; a second worker takes the job.
    with session(w.tenant_id, app_engine) as s:
        s.execute(
            text("update documents set lease_expires_at = now() - interval '1 minute' where id = :d"),
            {"d": str(doc.id)},
        )
    second = take(app_engine, w.tenant_id, doc.id)
    assert second is not None
    extracted = FakeExtractor().extract(data)
    # The late first worker completes while the row is still running for the same input: accepted.
    assert complete(app_engine, w.tenant_id, doc.id, sha, extracted) == "succeeded"
    assert complete(app_engine, w.tenant_id, doc.id, sha, extracted) == "discarded"
    with session(w.tenant_id, app_engine) as s:
        assert s.execute(text("select count(*) from extraction_runs where in_use")).scalar() == 1
        assert (
            s.execute(text("select state from documents where id = :d"), {"d": str(doc.id)}).scalar()
            == "succeeded"
        )
        assert s.execute(text("select count(*) from documents where state = 'running'")).scalar() == 0


def test_it07_batch_states_sum_and_retry_touches_only_failures(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "IT-07 tenant")
    files: list[bytes] = [fake_pdf(i) for i in range(228)]
    files += [fake_pdf(1000 + i, consistent=False) for i in range(9)]
    files += [fake_pdf(2000 + i, encrypted=True) for i in range(2)]
    files.append(files[0])  # byte-identical repeat
    assert len(files) == 240
    with session(w.tenant_id, app_engine) as s:
        batch = create_batch(s, w.tenant_id)
        for i, data in enumerate(files):
            add_file(s, w.tenant_id, w.user_id, batch.id, f"upload-{i}", data)
    while run_once(app_engine):
        pass
    with session(w.tenant_id, app_engine) as s:
        summary = batch_summary(s, batch.id)
    assert (summary["ready"], summary["needs review"], summary["failed"], summary["duplicate file"]) == (
        228,
        9,
        2,
        1,
    )
    assert sum(v for k, v in summary.items() if k != "file_count") == summary["file_count"] == 240
    with session(w.tenant_id, app_engine) as s:
        before = dict(
            s.execute(
                text("select id, state_version from documents where batch_id = :b"), {"b": str(batch.id)}
            ).all()
        )
        assert retry_failed(s, w.tenant_id, batch.id) == 2
    while run_once(app_engine):
        pass
    with session(w.tenant_id, app_engine) as s:
        after = dict(
            s.execute(
                text("select id, state_version from documents where batch_id = :b"), {"b": str(batch.id)}
            ).all()
        )
        changed = [d for d in after if after[d] != before[d]]
        failed = {r[0] for r in s.execute(text("select id from documents where state = 'failed'"))}
        assert set(changed) == failed and len(changed) == 2
        # Re-upload the whole batch with the same idempotency keys: no new documents.
        count = s.execute(text("select count(*) from documents")).scalar()
        for i, data in enumerate(files):
            add_file(s, w.tenant_id, w.user_id, batch.id, f"upload-{i}", data)
        assert s.execute(text("select count(*) from documents")).scalar() == count
        assert batch_summary(s, batch.id)["file_count"] == 240
    assert uuid.UUID(str(batch.id))


def test_unexpected_failure_after_the_lease_releases_the_document(app_engine, monkeypatch):  # type: ignore[no-untyped-def]
    """B4 regression: an error while storing a result left the document "running" and the job's
    retry skipped it, so the batch never finished. The document goes to retry_wait and the retry
    processes it."""
    from matchdesk.intake import process_document
    from matchdesk.intake import service as svc

    w = make_tenant(app_engine, "Fictional Distributor B4-lease")
    with session(w.tenant_id, app_engine) as s:
        batch = create_batch(s, w.tenant_id)
        doc = add_file(s, w.tenant_id, w.user_id, batch.id, "k", fake_pdf(77))
        doc_id = doc.id
    real = svc.materialise
    calls = {"n": 0}

    def flaky(*a, **k):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic failure while storing the result")
        return real(*a, **k)

    monkeypatch.setattr(svc, "materialise", flaky)
    with pytest.raises(RuntimeError):
        process_document(app_engine, w.tenant_id, doc_id, FakeExtractor())
    with session(w.tenant_id, app_engine) as s:
        assert s.get(DocumentRow, doc_id).state == "retry_wait"  # type: ignore[union-attr]
    assert process_document(app_engine, w.tenant_id, doc_id, FakeExtractor()) == "succeeded"
