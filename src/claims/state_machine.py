"""Claim status state machine for RefundAgent.

Defines valid status transitions between claim states and maps email
classification results to the appropriate new status. Enforces that only
valid transitions are applied, raising InvalidStatusTransitionError otherwise.
"""

import structlog

from src.extraction.classifier import EmailClassification
from src.models.claim import ClaimStatus

logger = structlog.get_logger(__name__)


class InvalidStatusTransitionError(Exception):
    """Raised when an invalid claim status transition is attempted.

    Attributes:
        current_status: The status the claim is currently in.
        attempted_status: The status that was attempted.
    """

    def __init__(self, current_status: ClaimStatus, attempted_status: ClaimStatus) -> None:
        """Initialise with current and attempted statuses.

        Args:
            current_status: The claim's current status.
            attempted_status: The status transition that was rejected.
        """
        super().__init__(
            f"Cannot transition from {current_status.value!r} to {attempted_status.value!r}."
        )
        self.current_status = current_status
        self.attempted_status = attempted_status


# Valid state transitions for the claim lifecycle
VALID_TRANSITIONS: dict[ClaimStatus, list[ClaimStatus]] = {
    ClaimStatus.DETECTED: [
        ClaimStatus.PENDING,
        ClaimStatus.RESOLVED,
        ClaimStatus.CLOSED,
    ],
    ClaimStatus.PENDING: [
        ClaimStatus.ACKNOWLEDGED,
        ClaimStatus.REJECTED,
        ClaimStatus.RESOLVED,
        ClaimStatus.CLOSED,
    ],
    ClaimStatus.ACKNOWLEDGED: [
        ClaimStatus.IN_REVIEW,
        ClaimStatus.REJECTED,
        ClaimStatus.RESOLVED,
    ],
    ClaimStatus.IN_REVIEW: [
        ClaimStatus.RESOLVED,
        ClaimStatus.REJECTED,
    ],
    ClaimStatus.REJECTED: [
        ClaimStatus.ESCALATED,
        ClaimStatus.CLOSED,
    ],
    ClaimStatus.ESCALATED: [
        ClaimStatus.RESOLVED,
        ClaimStatus.CLOSED,
    ],
    ClaimStatus.RESOLVED: [
        ClaimStatus.CLOSED,
    ],
    ClaimStatus.CLOSED: [],
}

# Maps email classification to the resulting claim status
CLASSIFICATION_TO_STATUS: dict[EmailClassification, ClaimStatus] = {
    EmailClassification.REFUND_CONFIRMED: ClaimStatus.RESOLVED,
    EmailClassification.REFUND_PENDING: ClaimStatus.PENDING,
    EmailClassification.REFUND_REJECTED: ClaimStatus.REJECTED,
    EmailClassification.CLAIM_ACKNOWLEDGED: ClaimStatus.ACKNOWLEDGED,
    EmailClassification.INFO_REQUESTED: ClaimStatus.PENDING,
}


def validate_transition(
    current_status: ClaimStatus,
    new_status: ClaimStatus,
) -> None:
    """Validate that a status transition is permitted.

    Logs a warning (without raising) if the transition is a no-op (same status).
    Raises InvalidStatusTransitionError if the transition is not in the allowed
    set for the current status.

    Args:
        current_status: The claim's current status.
        new_status: The desired new status.

    Returns:
        None

    Raises:
        InvalidStatusTransitionError: If the transition is not allowed.
    """
    if current_status == new_status:
        logger.warning(
            "state_machine.noop_transition",
            status=current_status.value,
        )
        return

    allowed = VALID_TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        raise InvalidStatusTransitionError(
            current_status=current_status,
            attempted_status=new_status,
        )

    logger.debug(
        "state_machine.transition_valid",
        from_status=current_status.value,
        to_status=new_status.value,
    )


def status_from_classification(
    classification: EmailClassification,
    current_status: ClaimStatus,
) -> ClaimStatus | None:
    """Derive the appropriate new claim status from an email classification.

    Returns None if the classification does not map to a status change
    (e.g. NOT_REFUND_RELATED, UNCERTAIN) or if the derived transition is
    not valid from the current status.

    Args:
        classification: The EmailClassification from the classifier.
        current_status: The claim's current status.

    Returns:
        ClaimStatus | None: The new status to apply, or None if no change.
    """
    target = CLASSIFICATION_TO_STATUS.get(classification)
    if target is None:
        return None

    try:
        validate_transition(current_status, target)
        return target
    except InvalidStatusTransitionError:
        logger.warning(
            "state_machine.invalid_transition_from_classification",
            classification=classification.value,
            current_status=current_status.value,
            target_status=target.value,
        )
        return None
