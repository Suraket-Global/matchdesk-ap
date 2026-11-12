"""Print the current one-time code of a local demo operator (B7; docs/PLAY.md). Development only:
reads the sealed TOTP seed of ``operator.demo@example.invalid`` (or the address given) from the
local database and prints the code for this 30-second step. Refuses in production."""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from sqlalchemy import select

from matchdesk.core import load_settings
from matchdesk.identity import User, code_at_step, step_at
from matchdesk.identity.secrets_box import unseal
from matchdesk.tenancy import get_engine, global_session

TOTP_CONTEXT = b"matchdesk:users.totp_secret_enc"  # identity.auth.TOTP_CONTEXT


def main() -> int:
    settings = load_settings()
    if settings.env == "production":
        print("operator-code: refused, MATCHDESK_ENV is production", file=sys.stderr)
        return 1
    email = sys.argv[1] if len(sys.argv) > 1 else "operator.demo@example.invalid"
    with global_session(get_engine(settings.database_url)) as s:
        user = s.scalar(select(User).where(User.email == email, User.is_operator.is_(True)))
        if user is None or user.totp_secret_enc is None:
            print(f"operator-code: no operator {email}; run make demo-reset", file=sys.stderr)
            return 1
        secret = unseal({settings.token_key_id: settings.token_key}, user.totp_secret_enc, TOTP_CONTEXT)
    now = datetime.now(UTC)
    left = 30 - int(now.timestamp()) % 30
    print(f"{code_at_step(secret, step_at(now))}  (valid for about {left} more seconds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
