"""AWS Lambda entry point for inbound SES email processing.

Invoked when SES receives an email at claims@{domain}, stores it to S3, then
calls this function via an SQS queue. The handler:

1. Parses the SES event to find the S3 key of the stored email.
2. Fetches and parses the raw email.
3. Stores extracted attachments back to S3.
4. Creates an email_events record (status=pending).
5. Classifies the email via Bedrock.
6. If refund-related, extracts structured claim data.
7. Upserts a Claim record.
8. Updates the email_events record (status=processed).

On any unhandled exception the email_events record is marked as failed and
the exception is re-raised so the SQS DLQ captures the message.
"""

import json
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from src.config import settings
from src.db.connection import get_session
from src.extraction.classifier import EmailClassification, classify_email
from src.extraction.extractor import extract_claim_data
from src.ingestion.email_parser import ParsedEmail, parse_raw_email, parse_ses_event
from src.ingestion.s3_store import fetch_raw_email, upload_attachment
from src.claims.manager import upsert_claim
from src.claims.state_machine import CLASSIFICATION_TO_STATUS
from src.models.claim import EmailEvent

logger = structlog.get_logger(__name__)

# Log a warning if processing exceeds this threshold (in seconds)
PROCESSING_WARN_THRESHOLD_SECONDS = 20


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for inbound SES email events.

    Args:
        event: The Lambda event payload from SES (via SQS).
        context: The Lambda context object (unused directly).

    Returns:
        dict: A response dict with statusCode and body.

    Raises:
        Exception: Re-raises any unhandled exception after marking the
            email_events record as failed, so SQS DLQ captures it.
    """
    start_time = time.monotonic()
    log = logger.bind(
        function_name=getattr(context, "function_name", "local"),
        aws_request_id=getattr(context, "aws_request_id", "local"),
    )
    log.info("ses_handler.invoked", record_count=len(event.get("Records", [])))

    # SQS wraps the SES event; unwrap if needed
    records = event.get("Records", [])
    if not records:
        log.warning("ses_handler.no_records")
        return {"statusCode": 200, "body": "No records to process"}

    # Handle SQS wrapper: body may be a JSON-encoded SES event
    raw_record = records[0]
    if raw_record.get("eventSource") == "aws:sqs":
        ses_event = json.loads(raw_record["body"])
    else:
        ses_event = event

    email_event_id: uuid.UUID | None = None

    try:
        # Step 1: Parse SES event to get S3 location
        bucket, s3_key = parse_ses_event(ses_event)
        log = log.bind(s3_key=s3_key)
        log.info("ses_handler.s3_location_found", bucket=bucket, key=s3_key)

        # Step 2: Fetch raw email from S3
        raw_bytes = fetch_raw_email(s3_key)
        log.info("ses_handler.email_fetched", size_bytes=len(raw_bytes))

        # Step 3: Parse the email
        parsed = parse_raw_email(raw_bytes)
        log = log.bind(message_id=parsed.message_id, sender=parsed.sender)
        log.info("ses_handler.email_parsed", subject=parsed.subject)

        # Step 4: Store attachments to S3
        attachment_keys = _store_attachments(parsed)

        # Step 5: Create email_events record
        with get_session() as session:
            email_event = EmailEvent(
                message_id=parsed.message_id or str(uuid.uuid4()),
                s3_key=s3_key,
                sender=parsed.sender,
                subject=parsed.subject,
                received_at=parsed.received_at,
                direction="inbound",
                processing_status="pending",
            )
            session.add(email_event)
            session.flush()
            email_event_id = email_event.id
            log = log.bind(email_event_id=str(email_event_id))
            log.info("ses_handler.email_event_created")

        # Step 6: Classify the email
        classification = classify_email(
            subject=parsed.subject,
            body_preview=parsed.body_text[:500],
        )
        log.info("ses_handler.classified", classification=classification.value)

        # Step 7: Extract claim data if refund-related
        claim_id = None
        extracted_data: dict = {}

        if classification != EmailClassification.NOT_REFUND_RELATED:
            claim_data = extract_claim_data(
                subject=parsed.subject,
                body=parsed.body_text or parsed.body_html or "",
            )
            extracted_data = claim_data.model_dump(mode="json")
            log.info(
                "ses_handler.extracted",
                merchant=claim_data.merchant,
                vertical=claim_data.vertical,
                confidence=claim_data.confidence,
            )

            # Step 8: Upsert claim
            with get_session() as session:
                claim = upsert_claim(
                    session=session,
                    claim_data=claim_data,
                    email_event_id=email_event_id,
                    classification=classification,
                )
                claim_id = claim.id
                log.info("ses_handler.claim_upserted", claim_id=str(claim_id))

        # Step 9: Update email_events with results
        with get_session() as session:
            ev = session.get(EmailEvent, email_event_id)
            if ev:
                ev.classification = classification.value
                ev.extracted_data = extracted_data
                ev.processing_status = "processed"
                if claim_id:
                    ev.claim_id = claim_id
            log.info("ses_handler.email_event_updated")

        elapsed = time.monotonic() - start_time
        if elapsed > PROCESSING_WARN_THRESHOLD_SECONDS:
            log.warning(
                "ses_handler.slow_processing",
                elapsed_seconds=round(elapsed, 2),
                threshold=PROCESSING_WARN_THRESHOLD_SECONDS,
            )
        else:
            log.info("ses_handler.complete", elapsed_seconds=round(elapsed, 2))

        return {"statusCode": 200, "body": json.dumps({"claim_id": str(claim_id)})}

    except Exception as exc:
        elapsed = time.monotonic() - start_time
        log.exception(
            "ses_handler.failed",
            error=str(exc),
            elapsed_seconds=round(elapsed, 2),
        )
        # Mark email event as failed so we know what to investigate
        if email_event_id is not None:
            try:
                with get_session() as session:
                    ev = session.get(EmailEvent, email_event_id)
                    if ev:
                        ev.processing_status = "failed"
                        ev.error_message = traceback.format_exc()[:2000]
            except Exception:
                log.exception("ses_handler.failed_to_mark_failure")

        raise  # Re-raise so SQS DLQ captures it


def _store_attachments(parsed: ParsedEmail) -> list[str]:
    """Upload all attachments from a parsed email to S3.

    Args:
        parsed: The parsed email containing attachments.

    Returns:
        list[str]: List of S3 keys for uploaded attachments.
    """
    keys = []
    for i, (filename, data) in enumerate(parsed.attachments, start=1):
        key = upload_attachment(
            message_id=parsed.message_id,
            index=i,
            filename=filename,
            data=data,
        )
        keys.append(key)
    return keys
