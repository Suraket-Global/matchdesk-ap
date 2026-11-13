"""Test-wide settings, fixed before any app or engine is built.

The default suite stores files in a temporary directory; the B2 MinIO tests select the S3
store explicitly. Session and token keys are random per run (test values only).
"""

from __future__ import annotations

import base64
import os
import secrets

os.environ["MATCHDESK_ENV"] = "test"
os.environ["MATCHDESK_BLOB_BACKEND"] = "local"
os.environ["MATCHDESK_SESSION_KEY"] = secrets.token_urlsafe(32)
os.environ["MATCHDESK_TOKEN_KEY"] = base64.b64encode(os.urandom(32)).decode()
os.environ["MATCHDESK_TOKEN_KEY_ID"] = "t1"
os.environ["MATCHDESK_APP_BASE_URL"] = "https://app.matchdesk.test"
os.environ["MATCHDESK_EXTRACTOR"] = "fake"
os.environ["MATCHDESK_QBO_MODE"] = "recorded"
# B11: tests never see the Intuit app credentials in backend/.env and never reach Intuit.
os.environ["MATCHDESK_QBO_CLIENT_ID"] = ""
os.environ["MATCHDESK_QBO_CLIENT_SECRET"] = ""
os.environ["MATCHDESK_QBO_REDIRECT_URI"] = ""
