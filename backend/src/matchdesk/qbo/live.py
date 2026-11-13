"""Which reader a tenant's sync uses (B11): recorded responses, or Intuit over its connection."""

from __future__ import annotations

import uuid

from sqlalchemy import Engine

from matchdesk.core import Settings
from matchdesk.qbo.client import DEFAULT_FIXTURES, IntuitQboReader, QboReader, RecordedQboReader
from matchdesk.qbo.intuit_http import IntuitApi
from matchdesk.qbo.oauth import (
    TokenEndpoint,
    get_connection,
    tenant_qbo_mode,
    token_endpoint_for,
    token_source,
)
from matchdesk.tenancy import session


def reader_for_tenant(
    engine: Engine, settings: Settings, tenant_id: uuid.UUID, endpoint: TokenEndpoint | None = None
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
    return IntuitQboReader(settings, IntuitApi(settings, realm, tokens))
