"""HTTP entry point (wiring only). Minimal core path of TRD section 12 for B1.

Tenant comes from the session, never from the URL or body. A record in another
tenant returns 404, identical to a missing record. Errors are problem+json with
the correlation ID.
"""

import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from matchdesk import blobstore
from matchdesk.core import (
    NotFoundError,
    configure_logging,
    get_correlation_id,
    get_logger,
    load_settings,
    new_correlation_id,
    set_correlation_id,
)
from matchdesk.exceptions import request_run
from matchdesk.exceptions.models import ExceptionRow, LineMatch, MatchRun
from matchdesk.identity import Principal, resolve_session
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow
from matchdesk.tenancy import get_engine, global_session, session
from matchdesk.tenancy.models import IdempotencyKey

log = get_logger("matchdesk.api")


class MatchRunRequest(BaseModel):
    invoice_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


def problem(status: int, title: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": title,
            "correlation_id": get_correlation_id(),
        },
    )


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="MatchDesk API", version="0.1.0", docs_url=None, redoc_url=None)

    def engine() -> Any:
        return get_engine(settings.database_url)

    @app.middleware("http")
    async def correlation(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        corr = request.headers.get("X-Correlation-Id")
        try:
            corr = str(uuid.UUID(corr)) if corr else new_correlation_id()
        except ValueError:
            corr = new_correlation_id()
        set_correlation_id(corr)
        started = time.monotonic()
        if request.url.path.startswith("/api/"):
            # Authenticate before the body is parsed or validated, so an anonymous caller gets
            # 401 and learns nothing about the request shape (B1-010).
            auth = request.headers.get("Authorization", "")
            p = None
            if auth.startswith("Bearer "):
                p = await run_in_threadpool(resolve_session, engine(), auth.removeprefix("Bearer ").strip())
            if p is None:
                denied = problem(401, "Not signed in")
                denied.headers["X-Correlation-Id"] = corr
                return denied
            request.state.principal = p
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = corr
        response.headers["Cache-Control"] = "no-store"
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return response

    @app.exception_handler(NotFoundError)
    async def not_found(_r: Request, _e: NotFoundError) -> JSONResponse:
        return problem(404, "Not found")

    @app.exception_handler(HTTPException)
    async def http_error(_r: Request, e: HTTPException) -> JSONResponse:
        return problem(e.status_code, str(e.detail))

    @app.exception_handler(RequestValidationError)
    async def invalid(_r: Request, _e: RequestValidationError) -> JSONResponse:
        # problem+json without echoing the submitted input (B1-010).
        return problem(422, "Request is not valid")

    def principal(request: Request) -> Principal:
        p = getattr(request.state, "principal", None)
        if p is None:
            raise HTTPException(401, "Not signed in")
        return p  # type: ignore[no-any-return]

    Auth = Annotated[Principal, Depends(principal)]

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        ok = True
        try:
            with global_session(engine()) as s:
                head = s.execute(text("select version_num from alembic_version")).scalar()
                ok = head is not None
        except Exception:
            ok = False
        try:
            root = settings.blob_root
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".ready"
            probe.write_bytes(b"1")
            probe.unlink()
        except OSError:
            ok = False
        return JSONResponse(
            status_code=200 if ok else 503, content={"status": "ready" if ok else "not ready"}
        )

    @app.post("/api/v1/match-runs", status_code=202)
    def create_match_run(
        body: MatchRunRequest,
        p: Auth,
        response: Response,
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        if p.role not in ("controller", "clerk"):
            raise HTTPException(403, "Forbidden")
        req_hash = str(sorted(str(i) for i in body.invoice_ids)).encode()
        try:
            return _create_match_run(p, body, req_hash, idempotency_key, response)
        except IntegrityError:
            # A concurrent request with the same key stored first: replay its result (B1-010).
            if not idempotency_key:
                raise
            with session(p.tenant_id, engine()) as s:
                replay = _replay(s, p, idempotency_key, req_hash)
            if replay is None:
                raise
            return replay

    def _replay(s: Any, p: Principal, key: str, req_hash: bytes) -> dict[str, Any] | None:
        seen = s.scalar(
            select(IdempotencyKey).where(IdempotencyKey.user_id == p.user_id, IdempotencyKey.key == key)
        )
        if seen is None:
            return None
        if seen.expires_at < datetime.now(UTC):
            s.delete(seen)  # an expired key is not replayed (B1-010)
            s.flush()
            return None
        if seen.request_hash != req_hash:
            raise HTTPException(409, "Idempotency key reused with a different request")
        run = s.get(MatchRun, seen.result_entity_id)
        assert run is not None
        return _run_body(run)

    def _create_match_run(
        p: Principal,
        body: MatchRunRequest,
        req_hash: bytes,
        idempotency_key: str | None,
        response: Response,
    ) -> dict[str, Any]:
        with session(p.tenant_id, engine()) as s:
            if idempotency_key:
                replay = _replay(s, p, idempotency_key, req_hash)
                if replay is not None:
                    return replay
            found = s.scalars(select(InvoiceRow.id).where(InvoiceRow.id.in_(body.invoice_ids))).all()
            if len(set(found)) != len(set(body.invoice_ids)):
                raise NotFoundError("invoice")
            run, created = request_run(s, p.tenant_id, list(body.invoice_ids))
            if idempotency_key:
                s.add(
                    IdempotencyKey(
                        tenant_id=p.tenant_id,
                        user_id=p.user_id,
                        key=idempotency_key,
                        request_hash=req_hash,
                        response_status=202,
                        result_entity_type="match_run",
                        result_entity_id=run.id,
                        expires_at=datetime.now(UTC) + timedelta(hours=24),
                    )
                )
            if not created:
                response.status_code = 200
            return _run_body(run)

    @app.get("/api/v1/match-runs/{run_id}")
    def get_match_run(run_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        with session(p.tenant_id, engine()) as s:
            run = s.get(MatchRun, run_id)
            if run is None:
                raise NotFoundError("match run")
            return _run_body(run)

    @app.get("/api/v1/invoices/{invoice_id}")
    def get_invoice(invoice_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        with session(p.tenant_id, engine()) as s:
            inv = s.get(InvoiceRow, invoice_id)
            if inv is None:
                raise NotFoundError("invoice")
            lines = s.scalars(
                select(InvoiceLineRow)
                .where(InvoiceLineRow.invoice_id == inv.id)
                .order_by(InvoiceLineRow.line_no)
            ).all()
            results = {
                lm.invoice_line_id: lm
                for lm in s.scalars(
                    select(LineMatch).where(
                        LineMatch.invoice_line_id.in_([ln.id for ln in lines]), LineMatch.is_current.is_(True)
                    )
                )
            }
            excs = s.scalars(select(ExceptionRow).where(ExceptionRow.invoice_id == inv.id)).all()
            return {
                "id": str(inv.id),
                "doc_type": inv.doc_type,
                "doc_number": inv.doc_number,
                "doc_date": inv.doc_date.isoformat() if inv.doc_date else None,
                "version": inv.version,
                "lines": [
                    {
                        "id": str(ln.id),
                        "line_no": ln.line_no,
                        "status": results[ln.id].status if ln.id in results else None,
                        "checks_run": results[ln.id].checks_run if ln.id in results else [],
                    }
                    for ln in lines
                ],
                "exceptions": [_exc_body(e) for e in excs],
            }

    @app.get("/api/v1/exceptions/{exception_id}")
    def get_exception(exception_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        with session(p.tenant_id, engine()) as s:
            e = s.get(ExceptionRow, exception_id)
            if e is None:
                raise NotFoundError("exception")
            return _exc_body(e)

    @app.get("/api/v1/documents/{document_id}/content")
    def get_document_content(document_id: uuid.UUID, p: Auth) -> Response:
        with session(p.tenant_id, engine()) as s:
            doc = s.get(DocumentRow, document_id)
            if doc is None or doc.deleted_at is not None:
                raise NotFoundError("document")
            data = blobstore.get(p.tenant_id, doc.blob_key, settings.blob_root)
            return Response(
                content=data,
                media_type=doc.mime_type,
                headers={
                    "Content-Disposition": f'attachment; filename="document-{doc.id}.pdf"',
                    "Content-Security-Policy": "sandbox",
                    "X-Content-Type-Options": "nosniff",
                },
            )

    return app


def _run_body(run: MatchRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "state": run.state,
        "state_version": run.state_version,
        "trigger": run.trigger,
        "lines_evaluated": run.lines_evaluated,
        "lines_matched": run.lines_matched,
        "exceptions_raised": run.exceptions_raised,
    }


def _exc_body(e: ExceptionRow) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "type": e.type,
        "sub_reason": e.sub_reason,
        "status": e.status,
        "value_class": e.value_class,
        "qualifying": e.qualifying,
        "resolution_code": e.resolution_code,
        "variance_qty": str(e.variance_qty) if e.variance_qty is not None else None,
        "variance_amount": str(e.variance_amount) if e.variance_amount is not None else None,
        "reported_amount": str(e.reported_amount) if e.reported_amount is not None else None,
        "invoice_line_id": str(e.invoice_line_id) if e.invoice_line_id else None,
        "label": e.label,
        "version": e.version,
    }


def main() -> None:
    import uvicorn

    settings = load_settings()
    configure_logging(settings.log_level)
    log.info("api_start", extra={"settings_hash": settings.fingerprint(), "service": "api"})
    uvicorn.run(
        create_app(), host=settings.api_host, port=settings.api_port, log_config=None, access_log=False
    )


if __name__ == "__main__":
    main()
