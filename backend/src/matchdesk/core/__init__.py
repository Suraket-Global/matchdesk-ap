"""Shared kernel: settings, logging, correlation, money, clock, errors. Standard library only."""

from matchdesk.core.clock import Clock, FixedClock, SystemClock
from matchdesk.core.errors import (
    ConflictError,
    ForbiddenError,
    MatchDeskError,
    NotFoundError,
    TenantContextError,
)
from matchdesk.core.logging import (
    configure_logging,
    get_correlation_id,
    get_logger,
    new_correlation_id,
    set_correlation_id,
    set_log_tenant,
)
from matchdesk.core.mail import Mailer, OutgoingMail, RecordingMailer, SmtpMailer, mailer_from_settings
from matchdesk.core.money import (
    CENT,
    ZERO,
    FloatNotAllowedError,
    dec,
    line_amount,
    round_cents,
    round_price,
    round_qty,
)
from matchdesk.core.pdf import text_pdf
from matchdesk.core.settings import Settings, SettingsError, load_settings

__all__ = [
    "CENT",
    "ZERO",
    "Clock",
    "ConflictError",
    "FixedClock",
    "FloatNotAllowedError",
    "ForbiddenError",
    "Mailer",
    "MatchDeskError",
    "NotFoundError",
    "OutgoingMail",
    "RecordingMailer",
    "Settings",
    "SettingsError",
    "SmtpMailer",
    "SystemClock",
    "TenantContextError",
    "configure_logging",
    "dec",
    "get_correlation_id",
    "get_logger",
    "line_amount",
    "load_settings",
    "mailer_from_settings",
    "new_correlation_id",
    "round_cents",
    "round_price",
    "round_qty",
    "set_correlation_id",
    "set_log_tenant",
    "text_pdf",
]
