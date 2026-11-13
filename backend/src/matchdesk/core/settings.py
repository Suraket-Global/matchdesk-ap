"""One typed settings object read from environment variables (TRD section 8.3).

Imported by both entry points. Standard library only, so the worker never pulls
a web framework in through configuration (R-07).

Values come from the process environment first, then from the gitignored file
named by ``MATCHDESK_ENV_FILE`` (default ``.env`` in the working directory).
Secrets (session key, token key, storage secret, SMTP password) have no default
outside ``dev`` and ``test`` and are never part of ``fingerprint()``.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

SECRET_FIELDS = frozenset(
    {
        "session_key",
        "token_key",
        "s3_secret_key",
        "smtp_password",
        "qbo_client_secret",
        "extraction_api_key",
        "inbound_signing_key",
    }
)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


class _Env:
    def __init__(self) -> None:
        self.file = _read_env_file(Path(os.environ.get("MATCHDESK_ENV_FILE", ".env")))

    def __call__(self, name: str, default: str) -> str:
        if name in os.environ:
            return os.environ[name]
        return self.file.get(name, default)


class SettingsError(RuntimeError):
    """A required setting is missing or invalid; the process refuses to start."""


@dataclass(frozen=True)
class Settings:
    env: str = "dev"
    # Application connection: non-superuser role subject to row-level security.
    database_url: str = "postgresql+psycopg://matchdesk_app@localhost:5432/matchdesk_dev"
    # Migration connection: the table owner (locally the OS superuser).
    migration_database_url: str = "postgresql+psycopg://zakria@localhost:5432/matchdesk_dev"
    api_host: str = "127.0.0.1"
    api_port: int = 8101
    # Proxies whose X-Forwarded-For is believed (IP addresses or CIDR ranges); empty = none (B2).
    trusted_proxies: tuple[str, ...] = ()
    log_level: str = "INFO"
    ruleset_code: str = "v1"
    tenant_currency_default: str = "CAD"
    job_lease_seconds: int = 300
    # Public origin of the web app; sign-in and invitation links are built from it.
    app_base_url: str = "http://127.0.0.1:5173"
    # HMAC key that derives each session's anti-forgery token from the session token (TRD 8.1).
    session_key: str = ""
    # AES-256-GCM key for TOTP seeds (and later QuickBooks tokens), base64 of 32 bytes; key id below.
    token_key: str = ""
    token_key_id: str = "k1"  # noqa: S105 (an identifier, not a secret)
    # Files: "local" (directory) or "s3" (S3 API; MinIO locally, a provider later).
    blob_backend: str = "local"
    blob_root: Path = field(default_factory=lambda: Path("var/blobs"))
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    # Outgoing mail over SMTP: Mailpit locally (127.0.0.1:1025, no auth); a provider later.
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_starttls: bool = False
    smtp_username: str = ""
    smtp_password: str = ""
    mail_from: str = "MatchDesk <no-reply@matchdesk.invalid>"
    # QuickBooks (B3): the server-wide default mode; since B11 a tenant may override it
    # (``tenants.qbo_mode``), so the recorded demo and an Intuit sandbox tenant run side by side.
    # "recorded" serves synthetic JSON fixtures shaped as the API is assumed to answer
    # (shape unverified until T-1.1.1); "intuit" selects the real endpoints, which stay unconfigured
    # (no developer account). Endpoint defaults are Intuit's documented URLs, unverified until T-1.1.1.
    qbo_mode: str = "recorded"
    qbo_fixtures_dir: str = ""
    qbo_client_id: str = ""
    qbo_client_secret: str = ""
    qbo_redirect_uri: str = ""
    qbo_authorize_url: str = "https://appcenter.intuit.com/connect/oauth2"
    qbo_token_url: str = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"  # noqa: S105
    qbo_revoke_url: str = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
    qbo_scopes: str = "com.intuit.quickbooks.accounting"
    qbo_page_size: int = 100
    # B11: the Accounting API host for tenants in "intuit" mode. Default: Intuit's sandbox host (a
    # production host is a separate decision). ``minorversion`` sent with every read [assumption]:
    # Intuit's 2025 notice that 75 is the lowest version served; confirmed or corrected by T-1.1.1.
    qbo_api_base_url: str = "https://sandbox-quickbooks.api.intuit.com"
    qbo_minor_version: str = "75"
    # Extraction (B3): "fake" (tests), "local" (text PDFs, no network, no model), "provider" (a hosted
    # model; deferred: needs an account, so it refuses to start without a key).
    extractor: str = "local"
    extraction_provider: str = ""
    extraction_api_key: str = ""
    # Email intake (B7, T-3.3.4): "local" accepts messages signed with HMAC-SHA256 under
    # ``inbound_signing_key`` (``make demo-email`` posts one); a hosted provider is selected by name
    # and refuses until its account exists. Addresses are ``<tenant local part>@<intake_domain>``.
    inbound_provider: str = "local"
    inbound_signing_key: str = ""
    intake_domain: str = "intake.matchdesk.invalid"
    # Weekly summary (B7, T-5.1.4): sent on Mondays from this hour, Pacific time, by the worker.
    weekly_summary_hour: int = 8
    # Local demo over plain HTTP only: cookies without the Secure flag and the __Host- prefix, because
    # Safari refuses Secure cookies on http://127.0.0.1 (the sign-in binding and the session then never
    # arrive). Allowed only when the web app is served from a loopback http address outside production.
    local_http_cookies: bool = False

    def fingerprint(self) -> str:
        """Hash of the non-secret settings; both entry points log it at start (CI-02)."""
        data = {k: v for k, v in asdict(self).items() if k not in SECRET_FIELDS}
        data["database_url"] = data["database_url"].split("@")[-1]
        data["migration_database_url"] = data["migration_database_url"].split("@")[-1]
        text = repr(sorted((k, str(v)) for k, v in data.items()))
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def require_secrets(self) -> None:
        """Refuse to start without the secrets the API needs (session key, token key)."""
        missing = [n for n in ("session_key", "token_key") if not getattr(self, n)]
        if self.blob_backend == "s3":
            missing += [n for n in ("s3_bucket", "s3_access_key", "s3_secret_key") if not getattr(self, n)]
        if missing:
            raise SettingsError("missing settings: " + ", ".join(sorted(missing)))
        if self.local_http_cookies and not self.loopback_http_app():
            raise SettingsError(
                "MATCHDESK_LOCAL_HTTP_COOKIES is for a local demo on http://127.0.0.1 or localhost only"
            )

    def loopback_http_app(self) -> bool:
        parts = urlsplit(self.app_base_url)
        return (
            self.env.lower() not in {"production", "prod"}
            and parts.scheme == "http"
            and parts.hostname in {"127.0.0.1", "localhost"}
        )


def load_settings() -> Settings:
    env = _Env()
    return Settings(
        env=env("MATCHDESK_ENV", "dev"),
        database_url=env("MATCHDESK_DATABASE_URL", Settings.database_url),
        migration_database_url=env("MATCHDESK_MIGRATION_DATABASE_URL", Settings.migration_database_url),
        api_host=env("MATCHDESK_API_HOST", "127.0.0.1"),
        api_port=int(env("MATCHDESK_API_PORT", "8101")),
        trusted_proxies=tuple(
            p.strip() for p in env("MATCHDESK_TRUSTED_PROXIES", "").split(",") if p.strip()
        ),
        log_level=env("MATCHDESK_LOG_LEVEL", "INFO"),
        ruleset_code=env("MATCHDESK_RULESET", "v1"),
        job_lease_seconds=int(env("MATCHDESK_JOB_LEASE_SECONDS", "300")),
        app_base_url=env("MATCHDESK_APP_BASE_URL", Settings.app_base_url).rstrip("/"),
        session_key=env("MATCHDESK_SESSION_KEY", ""),
        token_key=env("MATCHDESK_TOKEN_KEY", ""),
        token_key_id=env("MATCHDESK_TOKEN_KEY_ID", "k1"),
        blob_backend=env("MATCHDESK_BLOB_BACKEND", "local"),
        blob_root=Path(env("MATCHDESK_BLOB_ROOT", "var/blobs")),
        s3_endpoint_url=env("MATCHDESK_S3_ENDPOINT_URL", ""),
        s3_region=env("MATCHDESK_S3_REGION", "us-east-1"),
        s3_bucket=env("MATCHDESK_S3_BUCKET", ""),
        s3_access_key=env("MATCHDESK_S3_ACCESS_KEY", ""),
        s3_secret_key=env("MATCHDESK_S3_SECRET_KEY", ""),
        smtp_host=env("MATCHDESK_SMTP_HOST", "127.0.0.1"),
        smtp_port=int(env("MATCHDESK_SMTP_PORT", "1025")),
        smtp_starttls=env("MATCHDESK_SMTP_STARTTLS", "false").lower() == "true",
        smtp_username=env("MATCHDESK_SMTP_USERNAME", ""),
        smtp_password=env("MATCHDESK_SMTP_PASSWORD", ""),
        mail_from=env("MATCHDESK_MAIL_FROM", Settings.mail_from),
        qbo_mode=env("MATCHDESK_QBO_MODE", Settings.qbo_mode),
        qbo_fixtures_dir=env("MATCHDESK_QBO_FIXTURES_DIR", ""),
        qbo_client_id=env("MATCHDESK_QBO_CLIENT_ID", ""),
        qbo_client_secret=env("MATCHDESK_QBO_CLIENT_SECRET", ""),
        qbo_redirect_uri=env("MATCHDESK_QBO_REDIRECT_URI", ""),
        qbo_authorize_url=env("MATCHDESK_QBO_AUTHORIZE_URL", Settings.qbo_authorize_url),
        qbo_token_url=env("MATCHDESK_QBO_TOKEN_URL", Settings.qbo_token_url),
        qbo_revoke_url=env("MATCHDESK_QBO_REVOKE_URL", Settings.qbo_revoke_url),
        qbo_scopes=env("MATCHDESK_QBO_SCOPES", Settings.qbo_scopes),
        qbo_page_size=int(env("MATCHDESK_QBO_PAGE_SIZE", "100")),
        qbo_api_base_url=env("MATCHDESK_QBO_API_BASE_URL", Settings.qbo_api_base_url).rstrip("/"),
        qbo_minor_version=env("MATCHDESK_QBO_MINOR_VERSION", Settings.qbo_minor_version),
        extractor=env("MATCHDESK_EXTRACTOR", Settings.extractor),
        extraction_provider=env("MATCHDESK_EXTRACTION_PROVIDER", ""),
        extraction_api_key=env("MATCHDESK_EXTRACTION_API_KEY", ""),
        inbound_provider=env("MATCHDESK_INBOUND_PROVIDER", Settings.inbound_provider),
        inbound_signing_key=env("MATCHDESK_INBOUND_SIGNING_KEY", ""),
        intake_domain=env("MATCHDESK_INTAKE_DOMAIN", Settings.intake_domain),
        local_http_cookies=env("MATCHDESK_LOCAL_HTTP_COOKIES", "false").lower() == "true",
        weekly_summary_hour=int(env("MATCHDESK_WEEKLY_SUMMARY_HOUR", "8")),
    )
