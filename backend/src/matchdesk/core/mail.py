"""Outgoing mail behind one interface (TRD 3, 8.1; B2). Standard library only.

``SmtpMailer`` speaks plain SMTP: locally to Mailpit at 127.0.0.1:1025 without
authentication; in production to a provider's SMTP endpoint with STARTTLS and
credentials, selected by settings only. Message bodies are never logged.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from matchdesk.core.settings import Settings


@dataclass(frozen=True)
class OutgoingMail:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    def send(self, mail: OutgoingMail) -> None: ...


@dataclass
class SmtpMailer:
    host: str
    port: int
    sender: str
    starttls: bool = False
    username: str = ""
    password: str = ""
    timeout_seconds: int = 10

    def send(self, mail: OutgoingMail) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = mail.to
        msg["Subject"] = mail.subject
        msg.set_content(mail.body)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as smtp:
            if self.starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(msg)


@dataclass
class RecordingMailer:
    """Fake for unit tests: keeps messages in memory."""

    sent: list[OutgoingMail] = field(default_factory=list)

    def send(self, mail: OutgoingMail) -> None:
        self.sent.append(mail)


def mailer_from_settings(settings: Settings) -> Mailer:
    return SmtpMailer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.mail_from,
        starttls=settings.smtp_starttls,
        username=settings.smtp_username,
        password=settings.smtp_password,
    )
