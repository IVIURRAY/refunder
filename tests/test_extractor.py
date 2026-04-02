"""Tests for the email extractor module.

Mocks Bedrock responses to test JSON parsing, field extraction, and
error handling without requiring real AWS credentials.
"""

import json
from datetime import date

import pytest

from src.extraction.extractor import ClaimData, extract_claim_data
from src.models.claim import ClaimVertical


SAMPLE_EU261_JSON = {
    "merchant": "British Airways",
    "vertical": "uk261",
    "amount": 520.0,
    "currency": "GBP",
    "reference": "BA123456",
    "flight_number": "BA117",
    "flight_date": "2024-03-15",
    "departure_airport": "LHR",
    "arrival_airport": "JFK",
    "delay_hours": 4.5,
    "description": "British Airways UK261 compensation for flight BA117 LHR→JFK, 4.5 hour delay.",
    "confidence": 0.95,
}

SAMPLE_RETAIL_JSON = {
    "merchant": "Amazon",
    "vertical": "retail",
    "amount": 34.99,
    "currency": "GBP",
    "reference": "123-4567890-1234567",
    "flight_number": None,
    "flight_date": None,
    "departure_airport": None,
    "arrival_airport": None,
    "delay_hours": None,
    "description": "Amazon refund of £34.99 for order 123-4567890-1234567.",
    "confidence": 0.92,
}


class TestExtractClaimData:
    """Tests for extract_claim_data."""

    def test_eu261_extraction(self, mocker) -> None:
        mocker.patch(
            "src.extraction.extractor._call_bedrock_extractor",
            return_value=json.dumps(SAMPLE_EU261_JSON),
        )
        result = extract_claim_data(subject="UK261 claim", body="...")
        assert result.merchant == "British Airways"
        assert result.vertical == ClaimVertical.UK261
        assert result.amount == 520.0
        assert result.reference == "BA123456"
        assert result.flight_number == "BA117"
        assert result.flight_date == date(2024, 3, 15)
        assert result.departure_airport == "LHR"
        assert result.arrival_airport == "JFK"
        assert result.delay_hours == 4.5
        assert result.confidence == 0.95

    def test_retail_extraction(self, mocker) -> None:
        mocker.patch(
            "src.extraction.extractor._call_bedrock_extractor",
            return_value=json.dumps(SAMPLE_RETAIL_JSON),
        )
        result = extract_claim_data(subject="Refund for order", body="...")
        assert result.merchant == "Amazon"
        assert result.vertical == ClaimVertical.RETAIL
        assert result.amount == 34.99
        assert result.flight_number is None

    def test_markdown_fence_stripped(self, mocker) -> None:
        fenced = f"```json\n{json.dumps(SAMPLE_RETAIL_JSON)}\n```"
        mocker.patch(
            "src.extraction.extractor._call_bedrock_extractor",
            return_value=fenced,
        )
        result = extract_claim_data(subject="Refund", body="...")
        assert result.merchant == "Amazon"

    def test_malformed_json_returns_fallback(self, mocker) -> None:
        mocker.patch(
            "src.extraction.extractor._call_bedrock_extractor",
            return_value="This is not JSON at all",
        )
        mocker.patch("src.extraction.extractor.time.sleep")
        result = extract_claim_data(subject="Refund", body="...")
        assert result.merchant == "Unknown"
        assert result.vertical == ClaimVertical.UNKNOWN
        assert result.confidence == 0.1

    def test_raw_extraction_stored(self, mocker) -> None:
        mocker.patch(
            "src.extraction.extractor._call_bedrock_extractor",
            return_value=json.dumps(SAMPLE_EU261_JSON),
        )
        result = extract_claim_data(subject="Test", body="...")
        assert result.raw_extraction
        assert "merchant" in result.raw_extraction
