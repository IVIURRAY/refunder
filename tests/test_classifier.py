"""Tests for the email classifier module.

Uses pytest-mock to mock the Bedrock API call so tests run without
AWS credentials.
"""

import json

import pytest

from src.extraction.classifier import EmailClassification, classify_email


class TestClassifyEmail:
    """Tests for classify_email."""

    def test_classifies_refund_confirmed(self, mocker) -> None:
        mocker.patch(
            "src.extraction.classifier._call_bedrock",
            return_value="refund_confirmed",
        )
        result = classify_email(subject="Refund issued", body_preview="Your refund has been processed.")
        assert result == EmailClassification.REFUND_CONFIRMED

    def test_classifies_refund_pending(self, mocker) -> None:
        mocker.patch(
            "src.extraction.classifier._call_bedrock",
            return_value="refund_pending",
        )
        result = classify_email(subject="Refund processing", body_preview="We are processing your refund.")
        assert result == EmailClassification.REFUND_PENDING

    def test_classifies_not_refund_related(self, mocker) -> None:
        mocker.patch(
            "src.extraction.classifier._call_bedrock",
            return_value="not_refund_related",
        )
        result = classify_email(subject="Your monthly newsletter", body_preview="Check out our latest deals.")
        assert result == EmailClassification.NOT_REFUND_RELATED

    def test_unknown_response_returns_uncertain(self, mocker) -> None:
        mocker.patch(
            "src.extraction.classifier._call_bedrock",
            return_value="something_unexpected_xyz",
        )
        result = classify_email(subject="Hi", body_preview="Hello there")
        assert result == EmailClassification.UNCERTAIN

    def test_retries_on_exception_then_returns_uncertain(self, mocker) -> None:
        mocker.patch(
            "src.extraction.classifier._call_bedrock",
            side_effect=Exception("Connection error"),
        )
        mocker.patch("src.extraction.classifier.time.sleep")  # Skip backoff
        result = classify_email(subject="Refund", body_preview="Please process refund")
        assert result == EmailClassification.UNCERTAIN

    def test_body_preview_truncated_to_500_chars(self, mocker) -> None:
        mock_call = mocker.patch(
            "src.extraction.classifier._call_bedrock",
            return_value="refund_pending",
        )
        long_body = "x" * 2000
        classify_email(subject="Test", body_preview=long_body)
        _, kwargs = mock_call.call_args
        # The user_message should not contain more than 500 x's
        call_args = mock_call.call_args
        user_msg = call_args[1].get("user_message") or call_args[0][1]
        assert user_msg.count("x") <= 500
