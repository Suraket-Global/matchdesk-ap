"""IT-30 (C1, 2026-11-11): QuickBooks item-receipt exports are a receiving source, always class A."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from matchdesk.intake.models import DocumentRow
from matchdesk.receiving import QBO_ITEM_RECEIPT_SOURCE
from matchdesk.receiving.models import ReceivingImportRow
from matchdesk.tenancy import session

from .seed import make_tenant

pytestmark = pytest.mark.integration


def _import(engine, tenant_id, evidence_class: str) -> None:  # type: ignore[no-untyped-def]
    data = f"synthetic item-receipt export {uuid.uuid4()}".encode()
    with session(tenant_id, engine) as s:
        doc = DocumentRow(
            tenant_id=tenant_id,
            purpose="receiving",
            source="upload",
            blob_key=f"t/{tenant_id}/synthetic/{uuid.uuid4()}",
            sha256=hashlib.sha256(data).digest(),
            mime_type="text/csv",
            byte_size=len(data),
            state="succeeded",
            correlation_id=uuid.uuid4(),
        )
        s.add(doc)
        s.flush()
        s.add(
            ReceivingImportRow(
                tenant_id=tenant_id,
                source_type=QBO_ITEM_RECEIPT_SOURCE,
                evidence_class=evidence_class,
                document_id=doc.id,
                file_sha256=doc.sha256,
            )
        )


def test_it30_qbo_item_receipt_export_accepted_as_class_a(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Item receipt tenant")
    _import(app_engine, w.tenant_id, "A")


@pytest.mark.parametrize("evidence_class", ["B", "C"])
def test_it30_qbo_item_receipt_export_refused_unless_class_a(app_engine, evidence_class):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, f"Item receipt tenant {evidence_class}")
    with pytest.raises(IntegrityError, match="qbo_item_receipt_class_a"):
        _import(app_engine, w.tenant_id, evidence_class)
