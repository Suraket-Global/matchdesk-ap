# MatchDesk clickable demo

A one-page demo of the three-way match. All companies, suppliers, numbers and documents are invented.

- **Real rules:** `build_demo.py` passes a synthetic September 2026 month (6 purchase orders, 5 receipt lines, 8 invoices) to the real rule engine `matchdesk.matching.evaluate` and writes the results into `index.html`. Nothing in the page is hand-typed.
- **No QuickBooks needed:** no network, database or account is used. The QuickBooks connection is shown as a step only.
- **What it shows:** 1 matched invoice; 4 findings (billed more than received 770.00, price above PO 105.00, freight not on PO 95.00, duplicate invoice 170.00; total 1,140.00); 3 items that need a person and are not counted in dollars (receipt absent, item code not approved, no PO number).
- **Clickable:** dashboard, invoice list, invoice detail with PO vs received vs invoiced, resolve buttons (kept in the page only, not saved), report with print to PDF.

Open `index.html` in a browser. To rebuild after a rule change:

    PYTHONPATH=backend/src backend/.venv/bin/python demo/build_demo.py
