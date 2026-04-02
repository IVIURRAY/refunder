"""S3 storage utilities for raw emails and attachments.

Handles uploading raw email payloads and extracted attachments to S3,
following the bucket structure: {YYYY}/{MM}/{DD}/{message-id}.eml
"""

import mimetypes
from datetime import datetime, timezone
from typing import Optional

import boto3
import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


def get_s3_client():
    """Create a boto3 S3 client using application settings.

    Returns:
        boto3.client: Configured S3 client.
    """
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("s3", **kwargs)


def upload_raw_email(message_id: str, raw_bytes: bytes, received_at: Optional[datetime] = None) -> str:
    """Upload a raw email (.eml) to S3 under the date-partitioned prefix.

    Args:
        message_id: The email Message-ID header value (used as filename).
        raw_bytes: The complete RFC 2822 email as bytes.
        received_at: When the email was received; defaults to now (UTC).

    Returns:
        str: The S3 key under which the email was stored.

    Raises:
        botocore.exceptions.ClientError: If the S3 upload fails.
    """
    if received_at is None:
        received_at = datetime.now(timezone.utc)

    # Sanitise message_id for use as an S3 key component
    safe_id = message_id.strip("<>").replace("/", "_")
    date_prefix = received_at.strftime("%Y/%m/%d")
    s3_key = f"{date_prefix}/{safe_id}.eml"

    client = get_s3_client()
    client.put_object(
        Bucket=settings.raw_emails_bucket,
        Key=s3_key,
        Body=raw_bytes,
        ContentType="message/rfc822",
    )
    logger.info("s3.email.uploaded", bucket=settings.raw_emails_bucket, key=s3_key)
    return s3_key


def upload_attachment(message_id: str, index: int, filename: str, data: bytes) -> str:
    """Upload an email attachment to S3 nested under the message-id prefix.

    Args:
        message_id: The email Message-ID (used to build the S3 prefix).
        index: Attachment index (1-based) for deduplication.
        filename: Original filename of the attachment.
        data: Raw attachment bytes.

    Returns:
        str: The S3 key under which the attachment was stored.

    Raises:
        botocore.exceptions.ClientError: If the S3 upload fails.
    """
    safe_id = message_id.strip("<>").replace("/", "_")
    # Keep original extension; fall back to .bin
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    s3_key = f"{safe_id}/attachment-{index}.{ext}"

    content_type, _ = mimetypes.guess_type(filename)
    content_type = content_type or "application/octet-stream"

    client = get_s3_client()
    client.put_object(
        Bucket=settings.raw_emails_bucket,
        Key=s3_key,
        Body=data,
        ContentType=content_type,
    )
    logger.info(
        "s3.attachment.uploaded",
        bucket=settings.raw_emails_bucket,
        key=s3_key,
        filename=filename,
    )
    return s3_key


def fetch_raw_email(s3_key: str) -> bytes:
    """Download a raw email from S3.

    Args:
        s3_key: The S3 object key of the stored email.

    Returns:
        bytes: Raw email bytes (RFC 2822 format).

    Raises:
        botocore.exceptions.ClientError: If the object does not exist or access is denied.
    """
    client = get_s3_client()
    response = client.get_object(Bucket=settings.raw_emails_bucket, Key=s3_key)
    data = response["Body"].read()
    logger.info("s3.email.fetched", bucket=settings.raw_emails_bucket, key=s3_key)
    return data
