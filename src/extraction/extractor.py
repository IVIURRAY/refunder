"""Structured claim data extraction using Amazon Bedrock (Claude).

Called only for emails classified as refund-related. Sends the full email
body to Claude and parses the JSON response into a typed ClaimData model.

Includes retry logic with exponential backoff. On JSON parse failure, returns
a minimal ClaimData with low confidence rather than raising.
"""

import json
from datetime import date
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.extraction.classifier import get_bedrock_client
from src.extraction.prompts import EXTRACTOR_SYSTEM_PROMPT, EXTRACTOR_USER_TEMPLATE
from src.models.claim import ClaimVertical

logger = structlog.get_logger(__name__)


class ClaimData(BaseModel):
    """Structured claim data extracted from an email by Bedrock.

    This is a Pydantic model used to validate and type the raw JSON
    returned by the LLM before it is persisted to the database.
    """

    merchant: str
    vertical: ClaimVertical = ClaimVertical.UNKNOWN
    amount: Optional[float] = None
    currency: str = "GBP"
    reference: Optional[str] = None
    flight_number: Optional[str] = None
    flight_date: Optional[date] = None
    departure_airport: Optional[str] = None
    arrival_airport: Optional[str] = None
    delay_hours: Optional[float] = None
    description: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    raw_extraction: dict[str, Any] = Field(default_factory=dict)


def extract_claim_data(subject: str, body: str) -> ClaimData:
    """Extract structured claim data from an email using Bedrock.

    Sends the full email body to Claude with the extractor system prompt.
    Retries up to 3 times with exponential backoff. Returns a minimal
    ClaimData with confidence=0.1 if all retries fail or JSON parsing fails.

    Args:
        subject: The email subject line.
        body: The full plain-text (or HTML) email body.

    Returns:
        ClaimData: Extracted and validated claim data.
    """
    user_message = EXTRACTOR_USER_TEMPLATE.format(subject=subject, body=body)

    try:
        raw_response = _call_bedrock_extractor(user_message)
        claim_data = _parse_claim_data(raw_response)
        logger.info(
            "extractor.success",
            merchant=claim_data.merchant,
            vertical=claim_data.vertical.value,
            confidence=claim_data.confidence,
        )
        return claim_data
    except Exception as exc:
        logger.exception(
            "extractor.failed_all_retries",
            subject=subject,
            error=str(exc),
        )
        return ClaimData(
            merchant="Unknown",
            vertical=ClaimVertical.UNKNOWN,
            description="Extraction failed — manual review required.",
            confidence=0.1,
        )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _call_bedrock_extractor(user_message: str) -> str:
    """Make a Bedrock API call for extraction and return the raw response text.

    Args:
        user_message: The formatted user message including email content.

    Returns:
        str: Raw response text from the model.

    Raises:
        botocore.exceptions.ClientError: On AWS API errors.
    """
    client = get_bedrock_client()
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": EXTRACTOR_SYSTEM_PROMPT,
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


def _parse_claim_data(raw_text: str) -> ClaimData:
    """Parse the raw Bedrock response text into a ClaimData model.

    Strips markdown code fences if present before JSON parsing.

    Args:
        raw_text: Raw response text from Bedrock.

    Returns:
        ClaimData: Validated claim data model.

    Raises:
        json.JSONDecodeError: If the text is not valid JSON after stripping fences.
        pydantic.ValidationError: If the JSON does not match the ClaimData schema.
    """
    # Strip markdown fences: ```json ... ``` or ``` ... ```
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json or ```) and last line (```)
        cleaned = "\n".join(lines[1:-1]).strip()

    try:
        parsed_dict = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error(
            "extractor.json_parse_failed",
            raw_text=raw_text[:500],
        )
        raise

    # Inject the raw extraction for audit trail
    parsed_dict["raw_extraction"] = parsed_dict.copy()

    return ClaimData.model_validate(parsed_dict)
