"""Back-test reports (TRD 12; T-5.1.1, T-5.1.2, T-5.1.3 (c); B3). Wiring only."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import Engine, select

from matchdesk import reporting
from matchdesk.api.common import Auth, body_hash, idempotent_replay, page_limit, remember, require
from matchdesk.core import NotFoundError
from matchdesk.reporting.models import BacktestReport
from matchdesk.tenancy import session


class DraftBody(BaseModel):
    period_start: date
    period_end: date


def register_report_routes(app: FastAPI, engine: Engine) -> None:
    @app.post("/api/v1/reports/backtest", status_code=201)
    def post_draft(
        body: DraftBody,
        p: Auth,
        response: Response,
        idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
    ) -> dict[str, Any]:
        require(p, "draft_report")
        h = body_hash(body.model_dump(mode="json"))
        with session(p.tenant_id, engine) as s:
            seen = idempotent_replay(s, p, idempotency_key, h)
            if seen is not None:
                r = s.get(BacktestReport, seen[1])
                assert r is not None
                response.status_code = 200
                return reporting.describe_report(r)
            try:
                r = reporting.create_draft(s, p.tenant_id, p.user_id, body.period_start, body.period_end)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            remember(s, p, idempotency_key, h, 201, "backtest_report", r.id)
            return {
                **reporting.describe_report(r),
                "blocking": reporting.blocking_reasons(s, r.period_start, r.period_end),
            }

    @app.get("/api/v1/coverage")
    def get_coverage(p: Auth, period_start: date, period_end: date) -> dict[str, Any]:
        """Receipt coverage of a period from the current results (S-08 strip; B3/B4 review W3)."""
        require(p, "read")
        if period_end < period_start:
            raise HTTPException(422, "the period ends before it starts")
        with session(p.tenant_id, engine) as s:
            return reporting.live_coverage(s, period_start, period_end)

    @app.get("/api/v1/reports/backtest")
    def list_reports(p: Auth, cursor: uuid.UUID | None = None, limit: int | None = None) -> dict[str, Any]:
        require(p, "read")
        n = page_limit(limit)
        with session(p.tenant_id, engine) as s:
            q = select(BacktestReport).order_by(BacktestReport.id).limit(n + 1)
            if cursor is not None:
                q = q.where(BacktestReport.id > cursor)
            rows = s.scalars(q).all()
            return {
                "items": [reporting.describe_report(r) for r in rows[:n]],
                "next_cursor": str(rows[n - 1].id) if len(rows) > n else None,
            }

    def _load(s: Any, report_id: uuid.UUID) -> BacktestReport:
        r = s.get(BacktestReport, report_id)
        if r is None:
            raise NotFoundError("report")
        return r  # type: ignore[no-any-return]

    @app.get("/api/v1/reports/backtest/{report_id}")
    def get_report(report_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            r = _load(s, report_id)
            findings = reporting.findings_of(s, r.id)
            return {
                **reporting.describe_report(r),
                "blocking": reporting.blocking_reasons(s, r.period_start, r.period_end)
                if r.status == "draft"
                else [],
                "findings": [
                    {
                        "id": str(f.id),
                        "exception_id": str(f.exception_id),
                        "section": f.section,
                        "type": f.type,
                        "amount": str(f.amount),
                        "qualifying": f.qualifying,
                        "paid_status": f.paid_status,
                        "snapshot": f.snapshot,
                    }
                    for f in findings
                ],
            }

    @app.post("/api/v1/reports/backtest/{report_id}/approve")
    def post_approve(report_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        require(p, "approve_report")
        with session(p.tenant_id, engine) as s:
            r = reporting.approve(s, _load(s, report_id), p.user_id)
            return reporting.describe_report(r)

    @app.get("/api/v1/reports/backtest/{report_id}/export")
    def export(report_id: uuid.UUID, p: Auth, format: Literal["pdf", "csv"] = "pdf") -> Response:
        require(p, "export_report")
        with session(p.tenant_id, engine) as s:
            r = _load(s, report_id)
            findings = reporting.findings_of(s, r.id)
            data = reporting.export_pdf(r, findings) if format == "pdf" else reporting.export_csv(r, findings)
            kind = "draft" if r.status != "approved" else "approved"
            name = f"backtest-{r.period_start}-{r.period_end}-v{r.version_no}-{kind}.{format}"
            return Response(
                content=data,
                media_type="application/pdf" if format == "pdf" else "text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="{name}"',
                    "X-Content-Type-Options": "nosniff",
                },
            )

    @app.get("/api/v1/reports/backtest/{report_id}/refund-evaluation")
    def refund(report_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        # The threshold is the pilot term (schema.md pilot_engagements.refund_threshold, default
        # 500.00). That table is not built yet, so the server constant applies; a caller can no
        # longer choose it (B3/B4 review M6).
        threshold = reporting.DEFAULT_THRESHOLD
        require(p, "read")
        with session(p.tenant_id, engine) as s:
            r = _load(s, report_id)
            calc = reporting.refund_evaluation(r, threshold)
            return {
                "report_id": str(r.id),
                "report_status": r.status,
                "threshold": str(threshold),
                "qualifying_total": str(calc.qualifying_total),
                "unverified_total": str(calc.unverified_total),
                "refund_due": calc.refund_due,
            }
