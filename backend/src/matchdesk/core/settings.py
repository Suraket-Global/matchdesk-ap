"""One typed settings object read from environment variables (TRD section 8.3).

Imported by both entry points. Standard library only, so the worker never pulls
a web framework in through configuration (R-07).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    env: str = "dev"
    # Application connection: non-superuser role subject to row-level security.
    database_url: str = "postgresql+psycopg://matchdesk_app@localhost:5432/matchdesk_dev"
    # Migration connection: the table owner (locally the OS superuser).
    migration_database_url: str = "postgresql+psycopg://zakria@localhost:5432/matchdesk_dev"
    api_host: str = "127.0.0.1"
    api_port: int = 8101
    blob_root: Path = field(default_factory=lambda: Path("var/blobs"))
    log_level: str = "INFO"
    ruleset_code: str = "v1"
    tenant_currency_default: str = "CAD"
    job_lease_seconds: int = 300

    def fingerprint(self) -> str:
        """Hash of the non-secret settings; both entry points log it at start (CI-02)."""
        data = asdict(self)
        data["database_url"] = data["database_url"].split("@")[-1]
        data["migration_database_url"] = data["migration_database_url"].split("@")[-1]
        text = repr(sorted((k, str(v)) for k, v in data.items()))
        return hashlib.sha256(text.encode()).hexdigest()[:16]


def load_settings() -> Settings:
    return Settings(
        env=_env("MATCHDESK_ENV", "dev"),
        database_url=_env("MATCHDESK_DATABASE_URL", Settings.database_url),
        migration_database_url=_env("MATCHDESK_MIGRATION_DATABASE_URL", Settings.migration_database_url),
        api_host=_env("MATCHDESK_API_HOST", "127.0.0.1"),
        api_port=int(_env("MATCHDESK_API_PORT", "8101")),
        blob_root=Path(_env("MATCHDESK_BLOB_ROOT", "var/blobs")),
        log_level=_env("MATCHDESK_LOG_LEVEL", "INFO"),
        ruleset_code=_env("MATCHDESK_RULESET", "v1"),
        job_lease_seconds=int(_env("MATCHDESK_JOB_LEASE_SECONDS", "300")),
    )
