"""Build the MatchDesk clickable demo from the real rule engine.

Every company, supplier, number and document below is invented. No QuickBooks
account, network or database is used: the synthetic month is passed straight to
``matchdesk.matching.evaluate`` and its results are written into ``index.html``.

Run from the repository root:
    backend/.venv/bin/python demo/build_demo.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from matchdesk.matching import (
    Alias,
    AliasStatus,
    DocLine,
    DocType,
    Document,
    EvidenceClass,
    LineKind,
    MatchInput,
    PoLine,
    PurchaseOrder,
    ReceiptLine,
    ReceivingImport,
    VerificationStatus,
    evaluate,
)

HERE = Path(__file__).resolve().parent

VENDORS = {
    "v-north": "Northshore Fasteners (fictional)",
    "v-coast": "Coastline Pipe Supply (fictional)",
    "v-fraser": "Fraser Valve Co. (fictional)",
}

# (po id, vendor, number, date, [(line id, item, description, qty, uom, price)])
PO_SPEC = [
    (
        "po-5001",
        "v-north",
        "5001",
        date(2026, 9, 2),
        [("pl-5001-1", "it-bolt", "Hex bolt M12 x 50", "200", "EA", "0.85")],
    ),
    (
        "po-5002",
        "v-north",
        "5002",
        date(2026, 9, 4),
        [("pl-5002-1", "it-fit", "Brass fitting 3/4 in", "120", "EA", "38.50")],
    ),
    (
        "po-6001",
        "v-coast",
        "6001",
        date(2026, 9, 3),
        [("pl-6001-1", "it-pipe", "Copper pipe type L, per ft", "300", "FT", "6.40")],
    ),
    (
        "po-6002",
        "v-coast",
        "6002",
        date(2026, 9, 8),
        [("pl-6002-1", "it-elbow", "Copper elbow 90 deg", "150", "EA", "2.10")],
    ),
    (
        "po-7001",
        "v-fraser",
        "7001",
        date(2026, 9, 5),
        [("pl-7001-1", "it-valve", "Ball valve 2 in", "40", "EA", "112.00")],
    ),
    (
        "po-7002",
        "v-fraser",
        "7002",
        date(2026, 9, 9),
        [("pl-7002-1", "it-gate", "Gate valve 3 in", "10", "EA", "240.00")],
    ),
]

# supplier item code per (vendor, item); "it-gate" is a new code the clerk has not approved yet
ALIASES = [
    ("al-1", "v-north", "NF-M12-50", "it-bolt", True),
    ("al-2", "v-north", "NF-BR34", "it-fit", True),
    ("al-3", "v-coast", "CP-L-FT", "it-pipe", True),
    ("al-4", "v-coast", "CP-EL90", "it-elbow", True),
    ("al-5", "v-fraser", "FV-BV2", "it-valve", True),
    ("al-6", "v-fraser", "FV-GV3-NEW", "it-gate", False),
]

# warehouse receipts (class A): (id, po line, qty, date)
RECEIPTS = [
    ("r-1", "pl-5001-1", "200", date(2026, 9, 10)),
    ("r-2", "pl-5002-1", "100", date(2026, 9, 12)),
    ("r-3", "pl-6001-1", "300", date(2026, 9, 11)),
    ("r-4", "pl-6002-1", "150", date(2026, 9, 15)),
    ("r-6", "pl-7002-1", "10", date(2026, 9, 18)),
    # po-7001 (ball valves): nothing received yet
]

# invoices: (id, vendor, number, date, po, file, [(code, qty, uom, price, kind)], story)
INVOICES = [
    (
        "d-1",
        "v-north",
        "NF-1001",
        date(2026, 9, 14),
        "5001",
        "nf-1001.pdf",
        [("NF-M12-50", "200", "EA", "0.85", LineKind.ITEM)],
        "Ordered 200, received 200, billed 200 at the PO price.",
    ),
    (
        "d-2",
        "v-north",
        "NF-1002",
        date(2026, 9, 16),
        "5002",
        "nf-1002.pdf",
        [("NF-BR34", "120", "EA", "38.50", LineKind.ITEM)],
        "Billed for 120 fittings; the warehouse received 100.",
    ),
    (
        "d-3",
        "v-coast",
        "CP-2001",
        date(2026, 9, 15),
        "6001",
        "cp-2001.pdf",
        [("CP-L-FT", "300", "FT", "6.75", LineKind.ITEM)],
        "Quantity is right; the price is 6.75 instead of the PO's 6.40.",
    ),
    (
        "d-4",
        "v-coast",
        "CP-2002",
        date(2026, 9, 19),
        "6002",
        "cp-2002.pdf",
        [
            ("CP-EL90", "150", "EA", "2.10", LineKind.ITEM),
            (None, "1", None, "95.00", LineKind.FREIGHT),
        ],
        "Elbows match, but a 95.00 freight line was added that the PO does not allow.",
    ),
    (
        "d-5",
        "v-fraser",
        "FV-3001",
        date(2026, 9, 17),
        "7001",
        "fv-3001.pdf",
        [("FV-BV2", "40", "EA", "112.00", LineKind.ITEM)],
        "Billed for 40 ball valves; no receipt exists for this PO.",
    ),
    (
        "d-6",
        "v-north",
        "NF-1001",
        date(2026, 9, 22),
        "5001",
        "nf-1001-resent.pdf",
        [("NF-M12-50", "200", "EA", "0.85", LineKind.ITEM)],
        "The same invoice number from the same supplier, sent again as a new file.",
    ),
    (
        "d-7",
        "v-fraser",
        "FV-3002",
        date(2026, 9, 20),
        "7002",
        "fv-3002.pdf",
        [("FV-GV3-NEW", "10", "EA", "240.00", LineKind.ITEM)],
        "The supplier used a new item code; a person must approve what it maps to.",
    ),
    (
        "d-8",
        "v-coast",
        "CP-2003",
        date(2026, 9, 23),
        None,
        "cp-2003.pdf",
        [("CP-EL90", "20", "EA", "2.10", LineKind.ITEM)],
        "The invoice has no PO number, so it cannot be matched.",
    ),
]

EXPLAIN = {
    "qty_over_received": "Billed for more units than the warehouse received. Pay only for what arrived, or get a credit.",
    "price_variance": "The unit price is above the PO price beyond the tolerance (0.5% or 0.01).",
    "unmatched_charge": "A charge (freight or fee) that the PO does not include.",
    "receipt_absent": "Nothing has been received against this PO yet. Hold payment until it arrives.",
    "duplicate": "Same supplier and invoice number as one already checked. Paying it would pay twice.",
    "possible_duplicate": "Looks very similar to an earlier invoice. A person should check.",
    "alias_unconfirmed": "The supplier's item code is not yet approved, so the line was not checked.",
    "no_po": "No purchase order number on the invoice, so there is nothing to match against.",
}


def sha(name: str) -> bytes:
    return hashlib.sha256(name.encode()).digest()


def money(value: D | None) -> str | None:
    return None if value is None else f"{value.quantize(D('0.01'))}"


def build() -> dict:
    descriptions = {}
    pos = []
    for po_id, vendor, number, day, lines in PO_SPEC:
        pls = []
        for lid, item, desc, qty, uom, price in lines:
            descriptions[item] = desc
            pls.append(
                PoLine(
                    id=lid,
                    line_no=1,
                    item_id=item,
                    qty_ordered=D(qty),
                    uom=uom,
                    unit_price=D(price),
                )
            )
        pos.append(
            PurchaseOrder(
                id=po_id,
                vendor_id=vendor,
                po_number=number,
                txn_date=day,
                lines=tuple(pls),
            )
        )

    aliases = tuple(
        Alias(
            id=aid,
            vendor_id=vendor,
            supplier_item_code=code,
            item_id=item,
            status=AliasStatus.ACTIVE if ok else AliasStatus.PENDING_APPROVAL,
            approved=ok,
        )
        for aid, vendor, code, item, ok in ALIASES
    )
    imp = ReceivingImport(
        id="imp-sept",
        evidence_class=EvidenceClass.A,
        committed=True,
        declared_complete=True,
        coverage_start=date(2026, 9, 1),
        coverage_end=date(2026, 9, 30),
    )
    receipts = tuple(
        ReceiptLine(
            id=rid,
            import_id=imp.id,
            po_line_id=pl,
            qty_in_po_uom=D(qty),
            received_date=day,
        )
        for rid, pl, qty, day in RECEIPTS
    )

    docs = []
    for did, vendor, number, day, po, file, lines, _story in INVOICES:
        dls = []
        for n, (code, qty, uom, price, kind) in enumerate(lines, start=1):
            amount = (D(qty) * D(price)).quantize(D("0.01"))
            dls.append(
                DocLine(
                    id=f"{did}-l{n}",
                    line_no=n,
                    kind=kind,
                    supplier_item_code=code,
                    qty=D(qty) if kind == LineKind.ITEM else None,
                    uom=uom,
                    unit_price=D(price) if kind == LineKind.ITEM else None,
                    amount=amount,
                )
            )
        docs.append(
            Document(
                id=did,
                doc_type=DocType.INVOICE,
                vendor_id=vendor,
                doc_number=number,
                doc_date=day,
                file_sha256=sha(file),
                verification=VerificationStatus.PASSED,
                lines=tuple(dls),
                po_number=po,
                currency="CAD",
                total=sum((ln.amount or D(0) for ln in dls), D(0)),
            )
        )

    result = evaluate(
        MatchInput(
            tenant_currency="CAD",
            test_document_ids=frozenset(d.id for d in docs),
            documents=tuple(docs),
            purchase_orders=tuple(pos),
            aliases=aliases,
            receiving_imports=(imp,),
            receipt_lines=receipts,
        )
    )

    po_by_number = {(p.vendor_id, p.po_number): p for p in pos}
    received = {}
    for r in receipts:
        received[r.po_line_id] = received.get(r.po_line_id, D(0)) + r.qty_in_po_uom
    stories = {i[0]: i[7] for i in INVOICES}
    files = {i[0]: i[5] for i in INVOICES}

    out_docs = []
    for doc in docs:
        po = po_by_number.get((doc.vendor_id, doc.po_number or ""))
        lines = []
        for ln in doc.lines:
            lr = next((x for x in result.lines if x.line_id == ln.id), None)
            pl = (
                next((p for p in po.lines if lr and p.id == lr.po_line_id), None)
                if po
                else None
            )
            lines.append(
                {
                    "id": ln.id,
                    "kind": ln.kind.value,
                    "code": ln.supplier_item_code,
                    "description": descriptions.get(pl.item_id)
                    if pl and pl.item_id
                    else None,
                    "qty": money(ln.qty) if ln.qty is not None else None,
                    "uom": ln.uom,
                    "price": money(ln.unit_price),
                    "amount": money(ln.amount),
                    "status": lr.status.value if lr else "not_evaluated",
                    "po_qty": money(pl.qty_ordered) if pl else None,
                    "po_price": money(pl.unit_price) if pl else None,
                    "received": money(received.get(pl.id, D(0))) if pl else None,
                }
            )
        exc = [
            {
                "type": e.type.value,
                "line_id": e.line_id,
                "value_class": e.value_class.value,
                "amount": money(e.reported_amount),
                "variance_qty": money(e.variance_qty),
                "qualifying": e.qualifying,
                "explain": EXPLAIN.get(e.type.value, ""),
            }
            for e in result.exceptions_for(document_id=doc.id)
        ]
        out_docs.append(
            {
                "id": doc.id,
                "vendor": VENDORS[doc.vendor_id],
                "number": doc.doc_number,
                "date": doc.doc_date.isoformat() if doc.doc_date else None,
                "po": doc.po_number,
                "file": files[doc.id],
                "total": money(doc.total),
                "story": stories[doc.id],
                "lines": lines,
                "exceptions": exc,
            }
        )

    return {
        "company": "Sample Distributor Ltd. (fictional)",
        "month": "September 2026",
        "ruleset": result.ruleset_code,
        "purchase_orders": len(pos),
        "receipt_lines": len(receipts),
        "documents": out_docs,
    }


def main() -> None:
    data = build()
    template = (HERE / "template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, indent=1).replace("</", "<\\/")
    (HERE / "index.html").write_text(
        template.replace("__DEMO_DATA__", payload), encoding="utf-8"
    )
    for d in data["documents"]:
        kinds = (
            ", ".join(f"{e['type']} {e['amount']}" for e in d["exceptions"])
            or "matched"
        )
        print(f"{d['number']:8} {d['vendor'][:22]:22} -> {kinds}")


if __name__ == "__main__":
    main()
