"""Claim creation, update, and query operations.

All database access for the claims table lives here. Uses the upsert pattern:
first try to match an existing claim by reference number, then by merchant +
approximate amount within 90 days, and finally create a new claim.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from src.claims.state_machine import CLASSIFICATION_TO_STATUS, status_from_classification
from src.extraction.classifier import EmailClassification
from src.extraction.extractor import ClaimData
from src.models.claim import Claim, ClaimStatus

logger = structlog.get_logger(__name__)

# Tolerance for matching claims by amount (±10%)
AMOUNT_MATCH_TOLERANCE = 0.10
# How far back to look when matching by merchant+amount
LOOKBACK_DAYS = 90


def upsert_claim(
    session: Session,
    claim_data: ClaimData,
    email_event_id: uuid.UUID,
    classification: EmailClassification,
) -> Claim:
    """Create a new claim or update an existing one based on extracted data.

    Matching priority:
    1. Existing claim with the same reference number.
    2. Existing claim with the same merchant + approximate amount within 90 days.
    3. Create a new claim.

    Args:
        session: Active SQLAlchemy session.
        claim_data: Structured claim data extracted from the email.
        email_event_id: UUID of the associated EmailEvent record.
        classification: Email classification result used for status transition.

    Returns:
        Claim: The created or updated Claim ORM object.
    """
    existing: Optional[Claim] = None

    # Try to match by reference
    if claim_data.reference:
        existing = _get_by_reference(session, claim_data.reference)
        if existing:
            logger.info(
                "claim_manager.matched_by_reference",
                claim_id=str(existing.id),
                reference=claim_data.reference,
            )

    # Try to match by merchant + amount within 90 days
    if existing is None and claim_data.merchant and claim_data.amount:
        existing = _get_by_merchant_amount(
            session,
            merchant=claim_data.merchant,
            amount=claim_data.amount,
        )
        if existing:
            logger.info(
                "claim_manager.matched_by_merchant_amount",
                claim_id=str(existing.id),
                merchant=claim_data.merchant,
                amount=claim_data.amount,
            )

    if existing:
        return _update_existing_claim(session, existing, claim_data, classification)

    return _create_new_claim(session, claim_data)


def _create_new_claim(session: Session, claim_data: ClaimData) -> Claim:
    """Insert a new Claim record derived from ClaimData.

    Args:
        session: Active SQLAlchemy session.
        claim_data: Extracted claim information.

    Returns:
        Claim: The newly created and flushed Claim.
    """
    metadata: dict = {}
    if claim_data.flight_number:
        metadata["flight_number"] = claim_data.flight_number
    if claim_data.flight_date:
        metadata["flight_date"] = claim_data.flight_date.isoformat()
    if claim_data.departure_airport:
        metadata["departure_airport"] = claim_data.departure_airport
    if claim_data.arrival_airport:
        metadata["arrival_airport"] = claim_data.arrival_airport
    if claim_data.delay_hours is not None:
        metadata["delay_hours"] = claim_data.delay_hours

    claim = Claim(
        merchant=claim_data.merchant,
        vertical=claim_data.vertical,
        amount=Decimal(str(claim_data.amount)) if claim_data.amount else None,
        currency=claim_data.currency,
        reference=claim_data.reference,
        description=claim_data.description,
        status=ClaimStatus.DETECTED,
        metadata_=metadata,
    )
    session.add(claim)
    session.flush()
    logger.info(
        "claim_manager.created",
        claim_id=str(claim.id),
        merchant=claim.merchant,
        vertical=claim.vertical.value,
    )
    return claim


def _update_existing_claim(
    session: Session,
    claim: Claim,
    claim_data: ClaimData,
    classification: EmailClassification,
) -> Claim:
    """Update an existing claim with new data from a follow-up email.

    Args:
        session: Active SQLAlchemy session.
        claim: The existing Claim ORM object to update.
        claim_data: New extraction data from the latest email.
        classification: Email classification for status transition.

    Returns:
        Claim: The updated Claim object.
    """
    # Update amount if we now have a more precise value
    if claim_data.amount and claim.amount is None:
        claim.amount = Decimal(str(claim_data.amount))

    # Update description if provided and we have a richer one
    if claim_data.description and len(claim_data.description) > len(claim.description or ""):
        claim.description = claim_data.description

    # Apply status transition based on classification
    new_status = status_from_classification(classification, claim.status)
    if new_status and new_status != claim.status:
        old_status = claim.status
        claim.status = new_status
        claim.last_updated = datetime.now(timezone.utc)
        if new_status == ClaimStatus.RESOLVED:
            claim.resolved_at = datetime.now(timezone.utc)
            if claim_data.amount:
                claim.resolved_amount = Decimal(str(claim_data.amount))
        logger.info(
            "claim_manager.status_updated",
            claim_id=str(claim.id),
            from_status=old_status.value,
            to_status=new_status.value,
        )

    session.flush()
    return claim


def _get_by_reference(session: Session, reference: str) -> Optional[Claim]:
    """Look up a claim by its reference number.

    Args:
        session: Active SQLAlchemy session.
        reference: The booking/order reference to search for.

    Returns:
        Optional[Claim]: The matching claim, or None.
    """
    return session.query(Claim).filter(Claim.reference == reference).first()


def _get_by_merchant_amount(
    session: Session,
    merchant: str,
    amount: float,
) -> Optional[Claim]:
    """Look up a recent claim by merchant name and approximate amount.

    Args:
        session: Active SQLAlchemy session.
        merchant: Merchant name to match (case-insensitive).
        amount: Claimed amount; matches within ±AMOUNT_MATCH_TOLERANCE.

    Returns:
        Optional[Claim]: The most recent matching claim, or None.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    low = Decimal(str(amount * (1 - AMOUNT_MATCH_TOLERANCE)))
    high = Decimal(str(amount * (1 + AMOUNT_MATCH_TOLERANCE)))

    return (
        session.query(Claim)
        .filter(
            Claim.merchant.ilike(f"%{merchant}%"),
            Claim.amount.between(low, high),
            Claim.detected_at >= cutoff,
        )
        .order_by(Claim.detected_at.desc())
        .first()
    )


def get_claim_by_reference(session: Session, reference: str) -> Optional[Claim]:
    """Retrieve a claim by its reference number.

    Args:
        session: Active SQLAlchemy session.
        reference: The booking/order reference to look up.

    Returns:
        Optional[Claim]: The matching claim, or None if not found.
    """
    return _get_by_reference(session, reference)


def get_claim_by_id(session: Session, claim_id: uuid.UUID) -> Optional[Claim]:
    """Retrieve a claim by its primary key UUID.

    Args:
        session: Active SQLAlchemy session.
        claim_id: The UUID primary key of the claim.

    Returns:
        Optional[Claim]: The matching claim, or None if not found.
    """
    return session.get(Claim, claim_id)


def list_claims(
    session: Session,
    status: Optional[ClaimStatus] = None,
) -> list[Claim]:
    """List all claims, optionally filtered by status.

    Args:
        session: Active SQLAlchemy session.
        status: If provided, only return claims in this status.

    Returns:
        list[Claim]: Matching claims ordered by detected_at descending.
    """
    query = session.query(Claim)
    if status:
        query = query.filter(Claim.status == status)
    return query.order_by(Claim.detected_at.desc()).all()


def update_claim_status(
    session: Session,
    claim_id: uuid.UUID,
    new_status: ClaimStatus,
) -> Claim:
    """Manually update a claim's status, validating the transition.

    Args:
        session: Active SQLAlchemy session.
        claim_id: UUID of the claim to update.
        new_status: The desired new status.

    Returns:
        Claim: The updated Claim object.

    Raises:
        ValueError: If the claim does not exist.
        InvalidStatusTransitionError: If the transition is not valid.
    """
    from src.claims.state_machine import validate_transition

    claim = session.get(Claim, claim_id)
    if not claim:
        raise ValueError(f"Claim {claim_id} not found.")

    validate_transition(claim.status, new_status)
    claim.status = new_status
    claim.last_updated = datetime.now(timezone.utc)
    if new_status == ClaimStatus.RESOLVED:
        claim.resolved_at = datetime.now(timezone.utc)
    session.flush()
    return claim


def get_claims_due_for_chase(session: Session) -> list[Claim]:
    """Retrieve claims whose next_action_at is in the past.

    Args:
        session: Active SQLAlchemy session.

    Returns:
        list[Claim]: Claims due for a chase action, ordered by next_action_at.
    """
    # TODO (Phase 2): Integrate with the chase scheduler to auto-send follow-ups
    now = datetime.now(timezone.utc)
    return (
        session.query(Claim)
        .filter(
            Claim.next_action_at <= now,
            Claim.status.in_([
                ClaimStatus.DETECTED,
                ClaimStatus.PENDING,
                ClaimStatus.ACKNOWLEDGED,
                ClaimStatus.IN_REVIEW,
            ]),
        )
        .order_by(Claim.next_action_at.asc())
        .all()
    )
