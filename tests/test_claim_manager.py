"""Tests for the claim manager module.

Tests upsert logic, status updates, and query functions using an
in-memory SQLite database (via SQLAlchemy create_all).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.claims.manager import (
    get_claim_by_id,
    get_claim_by_reference,
    list_claims,
    update_claim_status,
    upsert_claim,
)
from src.claims.state_machine import InvalidStatusTransitionError
from src.extraction.classifier import EmailClassification
from src.extraction.extractor import ClaimData
from src.models.claim import Base, Claim, ClaimStatus, ClaimVertical


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite session for testing.

    Yields:
        Session: A transactional SQLAlchemy session backed by SQLite.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def make_claim_data(**overrides) -> ClaimData:
    """Build a ClaimData instance with sensible defaults.

    Args:
        **overrides: Field values to override.

    Returns:
        ClaimData: A test ClaimData instance.
    """
    defaults = {
        "merchant": "British Airways",
        "vertical": ClaimVertical.UK261,
        "amount": 520.0,
        "currency": "GBP",
        "reference": "BA123456",
        "description": "Test claim",
        "confidence": 0.9,
    }
    defaults.update(overrides)
    return ClaimData(**defaults)


class TestUpsertClaim:
    """Tests for the upsert_claim function."""

    def test_creates_new_claim(self, db_session) -> None:
        data = make_claim_data()
        claim = upsert_claim(
            db_session, data, uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED
        )
        assert claim.id is not None
        assert claim.merchant == "British Airways"
        assert claim.status == ClaimStatus.DETECTED

    def test_matches_by_reference(self, db_session) -> None:
        data = make_claim_data(reference="BA123456")
        claim1 = upsert_claim(
            db_session, data, uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED
        )
        # Second email with same reference — should update, not create
        data2 = make_claim_data(reference="BA123456")
        claim2 = upsert_claim(
            db_session, data2, uuid.uuid4(), EmailClassification.REFUND_CONFIRMED
        )
        assert claim1.id == claim2.id
        assert claim2.status == ClaimStatus.RESOLVED

    def test_creates_new_claim_when_no_reference_match(self, db_session) -> None:
        data1 = make_claim_data(reference="BA111111")
        data2 = make_claim_data(reference="BA999999")
        claim1 = upsert_claim(
            db_session, data1, uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED
        )
        claim2 = upsert_claim(
            db_session, data2, uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED
        )
        assert claim1.id != claim2.id

    def test_matches_by_merchant_and_amount(self, db_session) -> None:
        # First claim: no reference
        data1 = make_claim_data(reference=None, merchant="Hertz", amount=250.0)
        claim1 = upsert_claim(
            db_session, data1, uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED
        )
        # Second email: same merchant, similar amount, no reference
        data2 = make_claim_data(reference=None, merchant="Hertz", amount=250.0)
        claim2 = upsert_claim(
            db_session, data2, uuid.uuid4(), EmailClassification.REFUND_PENDING
        )
        assert claim1.id == claim2.id


class TestUpdateClaimStatus:
    """Tests for update_claim_status."""

    def test_valid_transition_succeeds(self, db_session) -> None:
        data = make_claim_data()
        claim = upsert_claim(
            db_session, data, uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED
        )
        updated = update_claim_status(db_session, claim.id, ClaimStatus.PENDING)
        assert updated.status == ClaimStatus.PENDING

    def test_invalid_transition_raises(self, db_session) -> None:
        data = make_claim_data()
        claim = upsert_claim(
            db_session, data, uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED
        )
        # Cannot go from DETECTED to IN_REVIEW directly
        with pytest.raises(InvalidStatusTransitionError):
            update_claim_status(db_session, claim.id, ClaimStatus.IN_REVIEW)

    def test_nonexistent_claim_raises(self, db_session) -> None:
        with pytest.raises(ValueError, match="not found"):
            update_claim_status(db_session, uuid.uuid4(), ClaimStatus.PENDING)


class TestListClaims:
    """Tests for list_claims."""

    def test_returns_all_claims(self, db_session) -> None:
        upsert_claim(db_session, make_claim_data(reference="R1"), uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED)
        upsert_claim(db_session, make_claim_data(reference="R2"), uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED)
        result = list_claims(db_session)
        assert len(result) == 2

    def test_filters_by_status(self, db_session) -> None:
        claim = upsert_claim(
            db_session, make_claim_data(reference="R1"), uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED
        )
        update_claim_status(db_session, claim.id, ClaimStatus.PENDING)
        upsert_claim(
            db_session, make_claim_data(reference="R2"), uuid.uuid4(), EmailClassification.CLAIM_ACKNOWLEDGED
        )
        pending = list_claims(db_session, status=ClaimStatus.PENDING)
        detected = list_claims(db_session, status=ClaimStatus.DETECTED)
        assert len(pending) == 1
        assert len(detected) == 1
