"""HTTP entry point (wiring only). Core path of TRD section 12 plus sign-in (B1, B2).

Tenant comes from the session cookie, never from the URL or body. A record in another
tenant returns 404, identical to a missing record. Errors are problem+json with
the correlation ID. Every mutating request of a signed-in session must carry the
session's anti-forgery token in ``X-CSRF-Token``.
"""

import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from matchdesk import blobstore
from matchdesk.api.auth_routes import PUBLIC_API_PATHS, register_auth_routes
from matchdesk.api.common import (
    CSRF_HEADER,
    MUTATING,
    SESSION_COOKIE,
    Auth,
    StaleVersion,
    conflict_response,
    problem,
    require,
)
from matchdesk.api.exception_routes import register_exception_routes
from matchdesk.api.invoice_routes import register_invoice_routes
from matchdesk.api.limits import MAX_FILE_BYTES, MAX_UPLOAD_FILE_BYTES, BodyLimitMiddleware
from matchdesk.api.qbo_routes import register_qbo_routes
from matchdesk.api.receiving_routes import register_receiving_routes
from matchdesk.api.report_routes import register_report_routes
from matchdesk.core import (
    ConflictError,
    ForbiddenError,
    Mailer,
    NotFoundError,
    configure_logging,
    get_logger,
    load_settings,
    mailer_from_settings,
    new_correlation_id,
    set_correlation_id,
)
from matchdesk.exceptions import request_run, stale_runs
from matchdesk.exceptions.models import ExceptionRow, LineMatch, MatchRun
from matchdesk.identity import Principal, csrf_matches, load_session
from matchdesk.intake import add_file, create_batch, describe_fields
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow, UploadBatch
from matchdesk.qbo import QboNotConfiguredError, TokenEndpoint, token_endpoint_from_settings
from matchdesk.tenancy import get_engine, global_session, session
from matchdesk.tenancy.models import IdempotencyKey

log = get_logger("matchdesk.api")

EXTENSIONS = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}


class MatchRunRequest(BaseModel):
    invoice_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


def sniff(data: bytes) -> str | None:
    """Content type from the bytes; the declared type and the file name are ignored (TRD 8.7)."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def _same_origin(request: Request, app_base_url: str) -> bool:
    """A browser sends ``Origin`` on every cross-origin POST; when present it must be the app's own."""
    origin = request.headers.get("Origin")
    return origin is None or origin.rstrip("/") == app_base_url.rstrip("/")


def create_app(mailer: Mailer | None = None, qbo_token_endpoint: TokenEndpoint | None = None) -> FastAPI:
    settings = load_settings()
    settings.require_secrets()
    app = FastAPI(title="MatchDesk API", version="0.2.0", docs_url=None, redoc_url=None)
    out_mail = mailer or mailer_from_settings(settings)

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
        path = request.url.path
        if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
            # Authenticate before the body is parsed or validated, so an anonymous caller gets
            # 401 and learns nothing about the request shape (B1-010). Only the cookie counts.
            token = request.cookies.get(SESSION_COOKIE)
            ctx = await run_in_threadpool(load_session, engine(), token) if token else None
            denied = None
            if ctx is None:
                denied = problem(401, "Not signed in")
            elif request.method in MUTATING and not csrf_matches(ctx, request.headers.get(CSRF_HEADER)):
                denied = problem(403, "Anti-forgery token missing or wrong")
            if denied is not None:
                denied.headers["X-Correlation-Id"] = corr
                denied.headers["Cache-Control"] = "no-store"
                return denied
            request.state.session = ctx
        elif path in PUBLIC_API_PATHS and not _same_origin(request, settings.app_base_url):
            # Public POSTs carry no session; a cross-site form post is refused by origin (ASVS 3.5.1).
            denied = problem(403, "Cross-site request refused")
            denied.headers["X-Correlation-Id"] = corr
            return denied
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = corr
        response.headers["Cache-Control"] = "no-store"
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return response

    register_auth_routes(app, settings, engine(), out_mail)
    qbo_endpoint: TokenEndpoint
    try:
        qbo_endpoint = qbo_token_endpoint or token_endpoint_from_settings(settings)
    except QboNotConfiguredError:  # Intuit selected but unconfigured: connect answers 503
        qbo_endpoint = _Unconfigured()
    register_qbo_routes(app, settings, engine(), qbo_endpoint)
    register_receiving_routes(app, engine())
    register_invoice_routes(app, engine())
    register_exception_routes(app, engine())
    register_report_routes(app, engine())
    # Outermost of the application's own middleware: refuses oversize bodies before anything reads them.
    app.add_middleware(BodyLimitMiddleware)

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

    @app.exception_handler(ForbiddenError)
    async def forbidden(_r: Request, _e: ForbiddenError) -> JSONResponse:
        return problem(403, "Forbidden")

    @app.exception_handler(StaleVersion)
    async def stale_version(_r: Request, e: StaleVersion) -> JSONResponse:
        return conflict_response(e.current)

    @app.exception_handler(ConflictError)
    async def conflict(_r: Request, e: ConflictError) -> JSONResponse:
        return problem(409, str(e) or "Conflict")

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
        ok = ok and blobstore.store(settings).ready()
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
        require(p, "start_match_run")
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
            body = _run_body(run)
            body["stale"] = bool(stale_runs(s, [run.id]).get(run.id)) if run.state == "succeeded" else None
            return body

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
            stale = stale_runs(s, [lm.match_run_id for lm in results.values()])
            run_of_match = {lm.id: lm.match_run_id for lm in results.values()}
            any_stale = any(stale.values())
            return {
                "stale": any_stale,
                "id": str(inv.id),
                "doc_type": inv.doc_type,
                "doc_number": inv.doc_number,
                "doc_date": inv.doc_date.isoformat() if inv.doc_date else None,
                "version": inv.version,
                "review": describe_fields(s, inv),
                "lines": [
                    {
                        "id": str(ln.id),
                        "line_no": ln.line_no,
                        **_line_status(results.get(ln.id), stale),
                        "checks_run": results[ln.id].checks_run if ln.id in results else [],
                    }
                    for ln in lines
                ],
                "exceptions": [
                    {
                        **_exc_body(e),
                        "stale": stale.get(run_of_match.get(e.line_match_id), any_stale)  # type: ignore[arg-type]
                        if e.line_match_id
                        else any_stale,
                    }
                    for e in excs
                ],
            }

    @app.get("/api/v1/exceptions/{exception_id}")
    def get_exception(exception_id: uuid.UUID, p: Auth) -> dict[str, Any]:
        with session(p.tenant_id, engine()) as s:
            e = s.get(ExceptionRow, exception_id)
            if e is None:
                raise NotFoundError("exception")
            body = _exc_body(e)
            lm = s.get(LineMatch, e.line_match_id) if e.line_match_id else None
            if lm is not None:
                body["stale"] = bool(stale_runs(s, [lm.match_run_id]).get(lm.match_run_id))
            else:
                runs = s.scalars(
                    select(LineMatch.match_run_id)
                    .join(InvoiceLineRow, InvoiceLineRow.id == LineMatch.invoice_line_id)
                    .where(InvoiceLineRow.invoice_id == e.invoice_id, LineMatch.is_current.is_(True))
                ).all()
                body["stale"] = any(stale_runs(s, list(runs)).values())
            return body

    @app.post("/api/v1/intake/batches", status_code=201)
    def post_batch(p: Auth) -> dict[str, Any]:
        require(p, "upload_and_receiving")
        with session(p.tenant_id, engine()) as s:
            batch = create_batch(s, p.tenant_id)
            return {"id": str(batch.id), "file_count": batch.file_count}

    @app.post("/api/v1/intake/batches/{batch_id}/files", status_code=201)
    async def post_file(
        batch_id: uuid.UUID,
        file: UploadFile,
        p: Auth,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ) -> dict[str, Any]:
        require(p, "upload_and_receiving")
        # The body limit middleware has already refused any request above MAX_UPLOAD_BODY_BYTES.
        data = await file.read(MAX_UPLOAD_FILE_BYTES + 1)
        mime = sniff(data)
        if mime is None:
            raise HTTPException(415, "Only PDF, PNG and JPEG invoices are accepted")
        if len(data) > MAX_FILE_BYTES[mime]:
            raise HTTPException(413, "File is larger than 20 MB")
        name = (file.filename or "")[:255] or None
        return await run_in_threadpool(_store_file, p, batch_id, idempotency_key, data, mime, name)

    def _store_file(
        p: Principal, batch_id: uuid.UUID, key: str, data: bytes, mime: str, name: str | None
    ) -> dict[str, Any]:
        with session(p.tenant_id, engine()) as s:
            if s.get(UploadBatch, batch_id) is None:
                raise NotFoundError("batch")
            doc = add_file(s, p.tenant_id, p.user_id, batch_id, key, data, mime, name)
            return {
                "id": str(doc.id),
                "state": doc.state,
                "byte_size": doc.byte_size,
                "mime_type": doc.mime_type,
            }

    @app.get("/api/v1/documents/{document_id}/content")
    def get_document_content(document_id: uuid.UUID, p: Auth) -> Response:
        with session(p.tenant_id, engine()) as s:
            doc = s.get(DocumentRow, document_id)
            if doc is None or doc.deleted_at is not None:
                raise NotFoundError("document")
            data = blobstore.get(p.tenant_id, doc.blob_key, settings=settings)
            ext = EXTENSIONS.get(doc.mime_type, "bin")
            return Response(
                content=data,
                media_type=doc.mime_type,
                headers={
                    "Content-Disposition": f'attachment; filename="document-{doc.id}.{ext}"',
                    "Content-Security-Policy": "sandbox",
                    "X-Content-Type-Options": "nosniff",
                },
            )

    return app


class _Unconfigured:
    """Token endpoint stand-in when ``MATCHDESK_QBO_MODE=intuit`` has no client configured."""

    def exchange(self, code: str, redirect_uri: str) -> dict[str, Any]:
        raise PermissionError("not configured")

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        raise PermissionError("not configured")

    def revoke(self, token: str) -> None:
        return None


def _line_status(lm: LineMatch | None, stale: dict[uuid.UUID, bool]) -> dict[str, Any]:
    """A result whose inputs changed since its run is shown as ``stale``, never as plain
    ``matched``; the earlier result stays visible as ``result_status`` (B1-001)."""
    if lm is None:
        return {"status": None, "result_status": None, "stale": False, "match_run_id": None}
    is_stale = bool(stale.get(lm.match_run_id))
    return {
        "status": "stale" if is_stale else lm.status,
        "result_status": lm.status,
        "stale": is_stale,
        "match_run_id": str(lm.match_run_id),
    }


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
    uvicorn.run(create_app(), **uvicorn_options(settings))


def uvicorn_options(settings: Any) -> dict[str, Any]:
    """Server options. Uvicorn's proxy-header trust is off: it would otherwise rewrite the client
    address from X-Forwarded-For for its default trusted host; ``api.limits.client_address`` decides."""
    return {
        "host": settings.api_host,
        "port": settings.api_port,
        "log_config": None,
        "access_log": False,
        "proxy_headers": False,
        "forwarded_allow_ips": "",
        "server_header": False,
    }


if __name__ == "__main__":
    main()
