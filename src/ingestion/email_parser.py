"""Parse raw SES events and RFC 2822 email payloads.

Extracts structured metadata (subject, sender, body text, attachments) from
the raw bytes stored in S3, and parses the SES Lambda event envelope to
locate those bytes.
"""

import email
import email.policy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ParsedEmail:
    """Structured representation of a parsed inbound email.

    Attributes:
        message_id: Value of the Message-ID header.
        sender: From address.
        subject: Email subject line.
        body_text: Plain-text body (may be empty if HTML-only).
        body_html: HTML body (may be None).
        received_at: Parsed Date header, or now() if missing/unparseable.
        attachments: List of (filename, bytes) tuples for each attachment.
        raw_headers: Dict of all header name→value pairs.
    """

    message_id: str
    sender: str
    subject: str
    body_text: str
    body_html: Optional[str]
    received_at: datetime
    attachments: list[tuple[str, bytes]] = field(default_factory=list)
    raw_headers: dict[str, str] = field(default_factory=dict)


def parse_ses_event(event: dict) -> tuple[str, str]:
    """Extract the S3 bucket and key from an SES Lambda invocation event.

    The SES receipt action stores the raw email in S3 before invoking Lambda.
    The event payload contains the bucket name and key.

    Args:
        event: The raw Lambda event dict from SES.

    Returns:
        tuple[str, str]: (bucket_name, s3_key)

    Raises:
        KeyError: If the event structure does not match the expected SES format.
        ValueError: If no S3 action is found in the receipt.
    """
    records = event["Records"]
    ses_record = records[0]["ses"]
    receipt = ses_record["receipt"]

    action = receipt.get("action", {})
    if action.get("type") != "S3":
        raise ValueError(
            f"Expected SES action type 'S3', got {action.get('type')!r}. "
            "Ensure your SES receipt rule is configured to store to S3."
        )

    bucket = action["bucketName"]
    key = action["objectKey"]
    logger.debug("ses.event.parsed", bucket=bucket, key=key)
    return bucket, key


def parse_raw_email(raw_bytes: bytes) -> ParsedEmail:
    """Parse a raw RFC 2822 email into a structured ParsedEmail object.

    Handles multipart messages, extracting plain text and HTML bodies
    separately, and collecting all non-inline attachments.

    Args:
        raw_bytes: The complete RFC 2822 email as bytes.

    Returns:
        ParsedEmail: Structured email data.

    Raises:
        ValueError: If the bytes cannot be decoded as a valid email message.
    """
    msg: EmailMessage = email.message_from_bytes(
        raw_bytes, policy=email.policy.default
    )  # type: ignore[assignment]

    message_id = msg.get("Message-ID", "").strip()
    sender = msg.get("From", "")
    subject = msg.get("Subject", "")

    # Parse received date
    received_at = _parse_date_header(msg.get("Date", ""))

    # Collect headers
    raw_headers = {k: v for k, v in msg.items()}

    body_text = ""
    body_html = None
    attachments: list[tuple[str, bytes]] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get_content_disposition() or "")

            if "attachment" in disposition:
                filename = part.get_filename() or f"attachment-{len(attachments)+1}"
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append((filename, payload))
            elif content_type == "text/plain" and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            elif content_type == "text/html" and body_html is None:
                payload = part.get_payload(decode=True)
                if payload:
                    body_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                body_html = decoded
            else:
                body_text = decoded

    logger.debug(
        "email.parsed",
        message_id=message_id,
        sender=sender,
        subject=subject,
        attachment_count=len(attachments),
        has_text=bool(body_text),
        has_html=bool(body_html),
    )

    return ParsedEmail(
        message_id=message_id,
        sender=sender,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        received_at=received_at,
        attachments=attachments,
        raw_headers=raw_headers,
    )


def _parse_date_header(date_str: str) -> datetime:
    """Parse an email Date header into a timezone-aware datetime.

    Args:
        date_str: Raw value of the Date header.

    Returns:
        datetime: Timezone-aware datetime; falls back to now(UTC) on failure.
    """
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        logger.warning("email.date.parse_failed", date_str=date_str)
        return datetime.now(timezone.utc)
