"""Switchable Resend / AWS SES sender. Safe to run in BackgroundTasks."""
import logging
from collections.abc import Iterable

import boto3

from app.config import get_settings

log = logging.getLogger(__name__)


def _dedupe(addresses: Iterable[str | None]) -> list[str]:
    seen: dict[str, None] = {}
    for a in addresses:
        if a and a.strip():
            seen.setdefault(a.strip().lower(), None)
    return list(seen)


def _chunks(items: list[str], n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]


def _send_resend(batch: list[str], subject: str, html: str) -> None:
    import resend

    s = get_settings()
    resend.api_key = s.resend_api_key
    # Resend needs a `to`; address it to the sender and BCC the batch.
    resend.Emails.send(
        {
            "from": s.email_from,
            "to": [s.email_from],
            "bcc": batch,
            "subject": subject,
            "html": html,
        }
    )


def _send_ses(batch: list[str], subject: str, html: str) -> None:
    s = get_settings()
    client = boto3.client(
        "ses",
        region_name=s.aws_region,
        aws_access_key_id=s.aws_access_key_id or None,
        aws_secret_access_key=s.aws_secret_access_key or None,
    )
    client.send_email(
        Source=s.email_from,
        Destination={"BccAddresses": batch},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
        },
    )


def send_batch_emails(recipients: list[str], subject: str, html_body: str) -> dict:
    """Send in BCC batches (default 50). Failures in one batch don't stop others."""
    s = get_settings()
    sender = _send_ses if s.email_provider == "ses" else _send_resend
    addresses = _dedupe(recipients)
    sent = failed = 0
    for batch in _chunks(addresses, s.email_batch_size):
        try:
            sender(batch, subject, html_body)
            sent += len(batch)
        except Exception:
            failed += len(batch)
            log.exception("Email batch failed (%d recipients)", len(batch))
    log.info("Email broadcast via %s: sent=%d failed=%d", s.email_provider, sent, failed)
    return {"sent": sent, "failed": failed}


def send_email(to: str, subject: str, html_body: str, text_body: str | None = None) -> None:
    """Send one transactional email (e.g. login codes). Raises on failure."""
    s = get_settings()
    if s.email_provider == "ses":
        client = boto3.client(
            "ses",
            region_name=s.aws_region,
            aws_access_key_id=s.aws_access_key_id or None,
            aws_secret_access_key=s.aws_secret_access_key or None,
        )
        body = {"Html": {"Data": html_body, "Charset": "UTF-8"}}
        if text_body:
            body["Text"] = {"Data": text_body, "Charset": "UTF-8"}
        client.send_email(
            Source=s.email_from,
            Destination={"ToAddresses": [to]},
            Message={"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": body},
        )
    else:
        import resend

        resend.api_key = s.resend_api_key
        resend.Emails.send(
            {"from": s.email_from, "to": [to], "subject": subject, "html": html_body, **({"text": text_body} if text_body else {})}
        )
