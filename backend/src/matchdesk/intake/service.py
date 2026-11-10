"""Invoice intake: batches, files, document processing with leases (MH-04; TRD 6.3; T-3.3.1 subset).

Processing a document is three short transactions: take the lease, extract
outside any transaction, then complete. Completion is accepted only while the
row is still ``running`` for the same input hash; a second completion finds it
finished and is discarded, so exactly one extraction run is in use (IT-06).
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from matchdesk import blobstore
from matchdesk.core import get_correlation_id, get_logger, new_correlation_id
from matchdesk.extraction import (
    Extracted,
    ExtractionPermanentError,
    ExtractionTransientError,
    Extractor,
    verification_gates,
)
from matchdesk.extraction.models import ExtractionRunRow
from matchdesk.intake.models import DocumentRow, UploadBatch
from matchdesk.tenancy import enqueue, session, transition
from matchdesk.tenancy.models import IdempotencyKey

log = get_logger("matchdesk.intake")
TASK = "process_document"
LEASE = timedelta(minutes=5)
MAX_ATTEMPTS = 4

# Stored state -> displayed state (TRD 6.3). Every stored state maps to exactly one.
DISPLAYED = {
    "queued": "queued",
    "retry_wait": "queued",
    "running": "processing",
    "succeeded": "ready",
    "needs_review": "needs review",
    "failed": "failed",
    "duplicate_file": "duplicate file",
}


def create_batch(s: Session, tenant_id: uuid.UUID) -> UploadBatch:
    batch = UploadBatch(tenant_id=tenant_id, source="upload")
    s.add(batch)
    s.flush()
    return batch


def add_file(
    s: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    batch_id: uuid.UUID,
    idempotency_key: str,
    data: bytes,
    mime_type: str = "application/pdf",
) -> DocumentRow:
    """Store one uploaded file. Idempotent on the key; a byte-identical file is ``duplicate_file``."""
    request_hash = hashlib.sha256(data).digest()
    seen = s.scalar(
        select(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == idempotency_key)
    )
    if seen is not None and seen.result_entity_id is not None:
        doc = s.get(DocumentRow, seen.result_entity_id)
        assert doc is not None
        return doc
    corr = get_correlation_id() or new_correlation_id()
    earlier = s.scalar(
        select(DocumentRow).where(
            DocumentRow.sha256 == request_hash,
            DocumentRow.purpose == "invoice",
            DocumentRow.state != "duplicate_file",
            DocumentRow.deleted_at.is_(None),
        )
    )
    key = blobstore.build_key(tenant_id, "invoice", data)
    doc = DocumentRow(
        tenant_id=tenant_id,
        purpose="invoice",
        source="upload",
        batch_id=batch_id,
        sha256=request_hash,
        mime_type=mime_type,
        byte_size=len(data),
        correlation_id=uuid.UUID(corr),
        blob_key=key if earlier is None else f"{key}/duplicate/{uuid.uuid4()}",
        state="queued" if earlier is None else "duplicate_file",
        duplicate_of_document_id=earlier.id if earlier is not None else None,
    )
    s.add(doc)
    s.flush()
    if earlier is None:
        blobstore.put(tenant_id, key, data)
        enqueue(s, TASK, tenant_id, {"document_id": str(doc.id)}, corr)
    s.execute(
        text("update upload_batches set file_count = file_count + 1 where id = :b"), {"b": str(batch_id)}
    )
    s.add(
        IdempotencyKey(
            tenant_id=tenant_id,
            user_id=user_id,
            key=idempotency_key,
            request_hash=request_hash,
            response_status=201,
            result_entity_type="document",
            result_entity_id=doc.id,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    s.flush()
    return doc


def batch_summary(s: Session, batch_id: uuid.UUID) -> dict[str, int]:
    batch = s.get(UploadBatch, batch_id)
    states = s.scalars(select(DocumentRow.state).where(DocumentRow.batch_id == batch_id)).all()
    counts = Counter(DISPLAYED[st] for st in states)
    summary = {name: counts.get(name, 0) for name in sorted(set(DISPLAYED.values()))}
    summary["file_count"] = batch.file_count if batch else 0
    return summary


def retry_failed(s: Session, tenant_id: uuid.UUID, batch_id: uuid.UUID) -> int:
    """Requeue failed files only; every other file is untouched."""
    failed = s.scalars(
        select(DocumentRow).where(DocumentRow.batch_id == batch_id, DocumentRow.state == "failed")
    ).all()
    n = 0
    for doc in failed:
        if transition(s, "documents", doc.id, doc.state_version, "queued", attempts=0, failure_code=None):
            enqueue(s, TASK, tenant_id, {"document_id": str(doc.id)}, str(doc.correlation_id))
            n += 1
    return n


def take(engine: Engine, tenant_id: uuid.UUID, document_id: uuid.UUID) -> tuple[bytes, int] | None:
    """Take the lease. Returns the file and the version written, or None if not takeable."""
    with session(tenant_id, engine) as s:
        doc = s.get(DocumentRow, document_id)
        if doc is None:
            return None
        now = datetime.now(UTC)
        expired = doc.state == "running" and doc.lease_expires_at is not None and doc.lease_expires_at < now
        if doc.state not in ("queued", "retry_wait") and not expired:
            return None
        if not transition(
            s,
            "documents",
            doc.id,
            doc.state_version,
            "running",
            lease_expires_at=now + LEASE,
            attempts=doc.attempts + 1,
        ):
            return None
        data = blobstore.get(tenant_id, doc.blob_key)
        return data, doc.state_version + 1


def complete(
    engine: Engine,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    input_sha: bytes,
    extracted: Extracted | None,
    error: Exception | None = None,
) -> str:
    """Write a result if the row is still running for this input; otherwise discard it."""
    with session(tenant_id, engine) as s:
        doc = s.get(DocumentRow, document_id, with_for_update=True)
        if doc is None or doc.state != "running" or doc.sha256 != input_sha:
            log.info("late_completion_discarded", extra={"entity_id": str(document_id)})
            return "discarded"
        if error is not None:
            permanent = isinstance(error, ExtractionPermanentError) or doc.attempts >= MAX_ATTEMPTS
            new_state = "failed" if permanent else "retry_wait"
            transition(
                s,
                "documents",
                doc.id,
                doc.state_version,
                new_state,
                lease_expires_at=None,
                failure_code=str(error) if permanent else type(error).__name__,
            )
            return new_state
        assert extracted is not None
        gates = verification_gates(extracted.output)
        passed = all(gates.values())
        s.execute(
            text("update extraction_runs set in_use = false where document_id = :d"), {"d": str(doc.id)}
        )
        run = ExtractionRunRow(
            tenant_id=tenant_id,
            document_id=doc.id,
            provider=extracted.provider,
            model=extracted.model,
            prompt_version=extracted.prompt_version,
            input_sha256=input_sha,
            status="succeeded",
            raw_output=extracted.output,
            verification=gates,
            correlation_id=doc.correlation_id,
            in_use=True,
        )
        s.add(run)
        s.flush()
        new_state = "succeeded" if passed else "needs_review"
        transition(s, "documents", doc.id, doc.state_version, new_state, lease_expires_at=None)
        return new_state


def process_document(
    engine: Engine, tenant_id: uuid.UUID, document_id: uuid.UUID, extractor: Extractor
) -> str:
    taken = take(engine, tenant_id, document_id)
    if taken is None:
        return "skipped"
    data, _version = taken
    sha = hashlib.sha256(data).digest()
    try:
        extracted = extractor.extract(data)
    except (ExtractionPermanentError, ExtractionTransientError) as exc:
        return complete(engine, tenant_id, document_id, sha, None, exc)
    return complete(engine, tenant_id, document_id, sha, extracted)


def make_handler(engine: Engine, extractor: Extractor) -> Any:
    def handler(_s: Session, payload: dict[str, Any]) -> None:
        process_document(
            engine, uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["document_id"]), extractor
        )

    return handler
