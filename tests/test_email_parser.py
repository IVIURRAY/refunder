"""Tests for the email parser module.

Verifies that raw RFC 2822 emails and SES event envelopes are correctly
parsed into structured data.
"""

import json
from pathlib import Path

import pytest

from src.ingestion.email_parser import parse_raw_email, parse_ses_event

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> bytes:
    """Load a fixture file as bytes.

    Args:
        name: Filename within tests/fixtures/.

    Returns:
        bytes: File contents.
    """
    return (FIXTURES / name).read_bytes()


class TestParseSesEvent:
    """Tests for parse_ses_event."""

    def test_parses_bucket_and_key(self) -> None:
        event = json.loads((FIXTURES / "sample_ses_event.json").read_text())
        bucket, key = parse_ses_event(event)
        assert bucket == "refundagent-raw-emails"
        assert "20240415092341" in key

    def test_raises_on_wrong_action_type(self) -> None:
        event = {
            "Records": [
                {
                    "ses": {
                        "receipt": {
                            "action": {"type": "Lambda", "functionArn": "arn:aws:lambda:..."}
                        }
                    }
                }
            ]
        }
        with pytest.raises(ValueError, match="Expected SES action type 'S3'"):
            parse_ses_event(event)

    def test_raises_on_missing_records(self) -> None:
        with pytest.raises(KeyError):
            parse_ses_event({})


class TestParseRawEmail:
    """Tests for parse_raw_email."""

    def test_eu261_email_parses_correctly(self) -> None:
        raw = load_fixture("sample_email_eu261.txt")
        parsed = parse_raw_email(raw)
        assert "BA117" in parsed.body_text
        assert parsed.subject == "Your UK261 Compensation Claim — Booking Reference BA123456"
        assert "britishairways" in parsed.sender
        assert parsed.message_id

    def test_retail_email_parses_correctly(self) -> None:
        raw = load_fixture("sample_email_retail.txt")
        parsed = parse_raw_email(raw)
        assert "34.99" in parsed.body_text
        assert "123-4567890" in parsed.subject

    def test_carrental_email_parses_correctly(self) -> None:
        raw = load_fixture("sample_email_carrental.txt")
        parsed = parse_raw_email(raw)
        assert "250" in parsed.body_text
        assert "RA-2024-987654" in parsed.subject

    def test_no_attachments_for_plain_text_email(self) -> None:
        raw = load_fixture("sample_email_eu261.txt")
        parsed = parse_raw_email(raw)
        assert parsed.attachments == []

    def test_received_at_is_timezone_aware(self) -> None:
        from datetime import timezone
        raw = load_fixture("sample_email_eu261.txt")
        parsed = parse_raw_email(raw)
        assert parsed.received_at.tzinfo is not None
