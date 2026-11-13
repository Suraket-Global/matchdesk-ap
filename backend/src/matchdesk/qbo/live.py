"""Which reader a tenant's sync uses (B11): recorded responses, or Intuit over its connection."""

from __future__ import annotations

import uuid

from sqlalchemy import Engine

from matchdesk.core import Settings, get_logger
from matchdesk.qbo.client import DEFAULT_FIXTURES, IntuitQboReader, QboReader, RecordedQboReader
from matchdesk.qbo.intuit_http import IntuitApi, Transport, urllib_get
from matchdesk.qbo.oauth import (
    TokenEndpoint,
    get_connection,
    tenant_qbo_mode,
    token_endpoint_for,
    token_source,
)
from matchdesk.tenancy import session

log = get_logger("matchdesk.qbo.live")


def reader_for_tenant(
    engine: Engine,
    settings: Settings,
    tenant_id: uuid.UUID,
    endpoint: TokenEndpoint | None = None,
    transport: Transport = urllib_get,
) -> QboReader:
    """The tenant's mode decides: ``recorded`` reads the fixtures; ``intuit`` reads its own realm
    with tokens refreshed through ``oauth.access_token``."""
    with session(tenant_id, engine) as s:
        mode = tenant_qbo_mode(s, settings, tenant_id)
        conn = get_connection(s)
        realm = conn.realm_id if conn is not None and conn.status == "connected" else None
    if mode != "intuit":
        return RecordedQboReader(settings.qbo_fixtures_dir or DEFAULT_FIXTURES)
    if realm is None:
        return IntuitQboReader(settings)
    tokens = token_source(engine, settings, endpoint or token_endpoint_for(settings, "intuit"), tenant_id)
    return IntuitQboReader(settings, IntuitApi(settings, realm, tokens, transport))


def read_company_name(
    engine: Engine,
    settings: Settings,
    tenant_id: uuid.UUID,
    endpoint: TokenEndpoint,
    transport: Transport = urllib_get,
) -> str | None:
    """After a connect: read CompanyInfo (one GET) and store ``CompanyName`` on the connection, so
    S-04 names the company. A failure leaves the name empty and the connection as it is."""
    with session(tenant_id, engine) as s:
        conn = get_connection(s)
        if conn is None or conn.status != "connected":
            return None
        realm = conn.realm_id
    try:
        api = IntuitApi(settings, realm, token_source(engine, settings, endpoint, tenant_id), transport)
        answer = api.company_info()
        name = answer.json().get("CompanyInfo", {}).get("CompanyName") if answer.ok else None
    except Exception:  # the connection stands; S-04 shows no name
        log.warning("qbo_company_info_failed", extra={"tenant_id": str(tenant_id)})
        return None
    if not name:
        return None
    with session(tenant_id, engine) as s:
        conn = get_connection(s)
        if conn is not None and conn.realm_id == realm:
            conn.company_name = str(name)
            conn.state_version += 1
    return str(name)
