"""Give an operator a fresh authenticator seed and print it once, for the owner's phone app.

Usage (on the server, by the owner only; the output is a secret and is never logged):
    dc --profile demo run --rm operator-code python scripts/operator_enroll.py ops@bitloomix.io

The user must already exist. The old seed stops working at once and the operator's open sessions
end (identity.enroll_operator). Scan the printed link as a QR code, or type the setup key into
Google Authenticator / Microsoft Authenticator ("Enter a setup key", time based).
"""

from __future__ import annotations

import sys

from matchdesk.core import load_settings
from matchdesk.identity import enroll_operator
from matchdesk.identity.totp import provisioning_uri, secret_b32
from matchdesk.tenancy import get_engine


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: operator_enroll.py <operator email>", file=sys.stderr)
        return 2
    email = sys.argv[1].strip().lower()
    settings = load_settings()
    secret = enroll_operator(get_engine(settings.database_url), email, settings)
    print("Authenticator set up for", email)
    print("Setup key (type it into the app, time based, 6 digits):", secret_b32(secret))
    print("Or open this link on the phone:", provisioning_uri(secret, email))
    print("Keep this private. Running this again replaces the key.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
