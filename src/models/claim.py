"""SQLAlchemy ORM models for claims and email events.

Defines the two core database tables:
- Claim: a single refund claim being tracked
- EmailEvent: an individual inbound (or future outbound) email linked to a claim

Uses SQLAlchemy 2.0 declarative style with full type annotations.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    CHAR,
    JSON,
    TEXT,
    UUID,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class ClaimVertical(str, enum.Enum):
    """The type/vertical of a refund claim."""

    EU261 = "eu261"
    UK261 = "uk261"
    RETAIL = "retail"
    CAR_RENTAL = "car_rental"
    SUBSCRIPTION = "subscription"
    UNKNOWN = "unknown"


class ClaimStatus(str, enum.Enum):
    """Lifecycle status of a claim."""

    DETECTED = "detected"
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    CLOSED = "closed"


class Claim(Base):
    """A refund claim being tracked by RefundAgent.

    Each claim corresponds to a single refund dispute with a merchant.
    Multiple email events can be linked to a single claim over its lifetime.
    """

    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    vertical: Mapped[ClaimVertical] = mapped_column(
        Enum(ClaimVertical, name="claim_vertical"),
        nullable=False,
        default=ClaimVertical.UNKNOWN,
    )
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), default="GBP")
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claim_status"),
        nullable=False,
        default=ClaimStatus.DETECTED,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    next_action_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSON, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    email_events: Mapped[list["EmailEvent"]] = relationship(
        "EmailEvent", back_populates="claim", lazy="select"
    )

    __table_args__ = (
        Index("idx_claims_status", "status"),
        Index("idx_claims_merchant", "merchant"),
        Index("idx_claims_vertical", "vertical"),
    )

    def __repr__(self) -> str:
        return (
            f"<Claim id={self.id} merchant={self.merchant!r} "
            f"status={self.status} amount={self.amount} {self.currency}>"
        )


class EmailEvent(Base):
    """An inbound (or future outbound) email associated with a claim.

    Stores the raw email metadata and the results of classification and
    extraction. The raw email body lives in S3; only the key is stored here.
    """

    __tablename__ = "email_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    claim_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_id: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    s3_key: Mapped[str] = mapped_column(TEXT, nullable=False)
    sender: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), default="inbound")
    classification: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    extracted_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=dict)
    processing_status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    claim: Mapped[Optional["Claim"]] = relationship("Claim", back_populates="email_events")

    __table_args__ = (
        Index("idx_email_events_claim_id", "claim_id"),
        Index("idx_email_events_message_id", "message_id"),
        Index("idx_email_events_processing_status", "processing_status"),
    )

    def __repr__(self) -> str:
        return (
            f"<EmailEvent id={self.id} message_id={self.message_id!r} "
            f"status={self.processing_status}>"
        )
