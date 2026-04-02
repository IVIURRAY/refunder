"""Email classification using Amazon Bedrock (Claude).

Determines whether an inbound email is refund-related and, if so, what
type of refund event it represents (confirmed, pending, rejected, etc.).

Uses a lightweight prompt with only the subject and a body preview to keep
latency and cost low. Includes exponential backoff retry on transient errors.
"""

import enum
import json
from typing import Optional

import boto3
import structlog
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.extraction.prompts import CLASSIFIER_SYSTEM_PROMPT, CLASSIFIER_USER_TEMPLATE

logger = structlog.get_logger(__name__)


class EmailClassification(str, enum.Enum):
    """Possible classification outcomes for an inbound email."""

    REFUND_CONFIRMED = "refund_confirmed"
    REFUND_PENDING = "refund_pending"
    REFUND_REJECTED = "refund_rejected"
    CLAIM_ACKNOWLEDGED = "claim_acknowledged"
    INFO_REQUESTED = "info_requested"
    NOT_REFUND_RELATED = "not_refund_related"
    UNCERTAIN = "uncertain"


def get_bedrock_client():
    """Create a boto3 Bedrock Runtime client.

    Returns:
        boto3.client: Configured Bedrock Runtime client.
    """
    kwargs: dict = {"region_name": settings.bedrock_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("bedrock-runtime", **kwargs)


def classify_email(subject: str, body_preview: str) -> EmailClassification:
    """Classify an inbound email using Bedrock.

    Passes only the subject and first 500 characters of the body to keep
    the prompt cheap and fast. Retries up to 3 times with exponential
    backoff on throttling or transient errors.

    Args:
        subject: The email subject line.
        body_preview: The first ~500 characters of the email body.

    Returns:
        EmailClassification: The classification result.
    """
    user_message = CLASSIFIER_USER_TEMPLATE.format(
        subject=subject,
        body_preview=body_preview[:500],
    )

    try:
        result = _call_bedrock(
            system_prompt=CLASSIFIER_SYSTEM_PROMPT,
            user_message=user_message,
        )
        classification = _parse_classification(result)
        logger.info("classifier.success", classification=classification.value)
        return classification
    except Exception as exc:
        logger.exception(
            "classifier.failed_all_retries",
            subject=subject,
            error=str(exc),
        )
        return EmailClassification.UNCERTAIN


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _call_bedrock(system_prompt: str, user_message: str) -> str:
    """Make a single Bedrock Claude API call and return the response text.

    Args:
        system_prompt: The system prompt to guide the model.
        user_message: The user message content.

    Returns:
        str: The model's response text, stripped of whitespace.

    Raises:
        ClientError: On AWS API errors.
        ValueError: If the response format is unexpected.
    """
    client = get_bedrock_client()
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 50,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    })

    response = client.invoke_model(
        modelId=settings.bedrock_model_id,
        contentType="application/json",
        accept="application/json",
        body=body,
    )

    response_body = json.loads(response["body"].read())
    return response_body["content"][0]["text"].strip()


def _parse_classification(raw_text: str) -> EmailClassification:
    """Parse Bedrock's raw text response into an EmailClassification enum.

    Args:
        raw_text: The raw text response from Bedrock.

    Returns:
        EmailClassification: The matched enum value, or UNCERTAIN if unknown.
    """
    cleaned = raw_text.lower().strip().rstrip(".")
    try:
        return EmailClassification(cleaned)
    except ValueError:
        logger.warning(
            "classifier.unknown_response",
            raw_text=raw_text,
            cleaned=cleaned,
        )
        return EmailClassification.UNCERTAIN
