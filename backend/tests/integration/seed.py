"""Synthetic tenants and golden fixture rows, written through ``tenancy.session`` as the app role."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal as D

from sqlalchemy import Engine

from matchdesk import blobstore
from matchdesk.exceptions.models import ItemAlias
from matchdesk.identity import Membership, Tenant, User, csrf_for, issue_session
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow
from matchdesk.matching import normalise_code, normalise_number
from matchdesk.qbo.models import Item, PoLineRow, PurchaseOrderRow, Vendor
from matchdesk.receiving.models import ReceiptLineRow, ReceiptRow, ReceivingImportRow
from matchdesk.tenancy import global_session, session

NOW = datetime(2026, 11, 1, tzinfo=UTC)


@dataclass
class World:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    token: str
    vendor_id: uuid.UUID
    item_id: uuid.UUID
    po_id: uuid.UUID
    po_line_id: uuid.UUID
    alias_id: uuid.UUID
    import_id: uuid.UUID | None = None
    invoices: dict[str, uuid.UUID] = field(default_factory=dict)
    documents: dict[str, uuid.UUID] = field(default_factory=dict)

    @property
    def headers(self) -> dict[str, str]:
        """Fixture session: the session cookie and its anti-forgery token (B2; replaces B1 bearer)."""
        return auth_headers(self.token)


def auth_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"__Host-md_session={token}", "X-CSRF-Token": csrf_for(token)}


def make_tenant(engine: Engine, name: str, role: str = "clerk") -> World:
    with global_session(engine) as s:
        t = Tenant(name=name)
        u = User(email=f"{uuid.uuid4().hex[:8]}@example.invalid", display_name="Synthetic user")
        s.add_all([t, u])
        s.flush()
        tid, uid = t.id, u.id
    with session(tid, engine) as s:
        s.add(Membership(tenant_id=tid, user_id=uid, role=role))
        v = Vendor(tenant_id=tid, qbo_id="V1", name="Fictional Supplier T", synced_at=NOW)
        it = Item(tenant_id=tid, qbo_id="I1", name="Synthetic widget", synced_at=NOW)
        s.add_all([v, it])
        s.flush()
        po = PurchaseOrderRow(
            tenant_id=tid,
            qbo_id="PO1",
            vendor_id=v.id,
            po_number="4471",
            po_number_norm=normalise_number("4471"),
            txn_date=date(2026, 9, 1),
            synced_at=NOW,
        )
        s.add(po)
        s.flush()
        pl = PoLineRow(
            tenant_id=tid,
            purchase_order_id=po.id,
            qbo_line_id="2",
            line_no=2,
            item_id=it.id,
            qty_ordered=D("100"),
            uom="EA",
            unit_price=D("4.20"),
        )
        al = ItemAlias(
            tenant_id=tid,
            vendor_id=v.id,
            supplier_item_code="W-100",
            supplier_item_code_norm=normalise_code("W-100"),
            item_id=it.id,
            status="active",
            created_by=uid,
        )
        s.add_all([pl, al])
        s.flush()
        world = World(tid, uid, "", v.id, it.id, po.id, pl.id, al.id)
    world.token = issue_session(engine, uid, tid)
    return world


def add_invoice(
    engine: Engine,
    w: World,
    key: str,
    number: str,
    day: date,
    qty: str,
    price: str = "4.20",
    doc_type: str = "invoice",
    references: str | None = None,
    uom: str = "EA",
) -> uuid.UUID:
    data = f'%FAKE-PDF\n{{"synthetic": "{key}-{w.tenant_id}"}}'.encode()
    sha = hashlib.sha256(data).digest()
    with session(w.tenant_id, engine) as s:
        bkey = blobstore.build_key(w.tenant_id, "invoice", data)
        blobstore.put(w.tenant_id, bkey, data)
        doc = DocumentRow(
            tenant_id=w.tenant_id,
            purpose="invoice",
            source="upload",
            blob_key=bkey,
            sha256=sha,
            mime_type="application/pdf",
            byte_size=len(data),
            state="succeeded",
            correlation_id=uuid.uuid4(),
        )
        s.add(doc)
        s.flush()
        amount = (D(qty) * D(price)).quantize(D("0.01"))
        inv = InvoiceRow(
            tenant_id=w.tenant_id,
            document_id=doc.id,
            file_order_key=sha,
            doc_type=doc_type,
            vendor_id=w.vendor_id,
            doc_number=number,
            doc_number_norm=normalise_number(number),
            doc_date=day,
            po_number_read="4471",
            total=amount,
            currency="CAD",
            verification_status="passed",
            references_invoice_number=references,
        )
        s.add(inv)
        s.flush()
        s.add(
            InvoiceLineRow(
                tenant_id=w.tenant_id,
                invoice_id=inv.id,
                line_no=1,
                supplier_item_code="W-100",
                qty=D(qty),
                uom=uom,
                unit_price=None if doc_type == "credit_note" else D(price),
                amount=amount,
            )
        )
        w.invoices[key] = inv.id
        w.documents[key] = doc.id
        return inv.id


def add_receipt(
    engine: Engine, w: World, qty: str, day: date, evidence_class: str = "A", row: int = 1
) -> None:
    with session(w.tenant_id, engine) as s:
        if w.import_id is None:
            data = f"synthetic receiving {w.tenant_id} {evidence_class}".encode()
            bkey = blobstore.build_key(w.tenant_id, "receiving", data)
            blobstore.put(w.tenant_id, bkey, data)
            doc = DocumentRow(
                tenant_id=w.tenant_id,
                purpose="receiving",
                source="upload",
                blob_key=bkey,
                sha256=hashlib.sha256(data).digest(),
                mime_type="text/csv",
                byte_size=len(data),
                state="succeeded",
                correlation_id=uuid.uuid4(),
            )
            s.add(doc)
            s.flush()
            imp = ReceivingImportRow(
                tenant_id=w.tenant_id,
                source_type="spreadsheet",
                evidence_class=evidence_class,
                document_id=doc.id,
                file_sha256=doc.sha256,
                state="succeeded",
                committed_at=NOW,
            )
            s.add(imp)
            s.flush()
            w.import_id = imp.id
        r = ReceiptRow(
            tenant_id=w.tenant_id,
            receiving_import_id=w.import_id,
            purchase_order_id=w.po_id,
            received_date=day,
        )
        s.add(r)
        s.flush()
        s.add(
            ReceiptLineRow(
                tenant_id=w.tenant_id,
                receipt_id=r.id,
                receiving_import_id=w.import_id,
                po_line_id=w.po_line_id,
                qty_received=D(qty),
                qty_in_po_uom=D(qty),
                source_row=row,
            )
        )


def add_user(engine: Engine, w: World, role: str) -> tuple[uuid.UUID, dict[str, str]]:
    """A second synthetic user in the same tenant; returns (user id, request headers)."""
    with global_session(engine) as s:
        u = User(email=f"{uuid.uuid4().hex[:8]}@example.invalid", display_name=f"Synthetic {role}")
        s.add(u)
        s.flush()
        uid = u.id
    with session(w.tenant_id, engine) as s:
        s.add(Membership(tenant_id=w.tenant_id, user_id=uid, role=role))
    return uid, auth_headers(issue_session(engine, uid, w.tenant_id))
