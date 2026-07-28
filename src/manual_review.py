from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.state_manager import ClaimStatus


class ManualReviewStatus(StrEnum):
    """
    Supported manual-review queue statuses.
    """

    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class ReviewerDecision(StrEnum):
    """
    Decisions a simulated reviewer may make.
    """

    APPROVED = "APPROVED"
    DENIED = "DENIED"


@dataclass(frozen=True)
class ManualReviewDecision:
    """
    One synthetic reviewer decision.
    """

    claim_id: str
    decision: ReviewerDecision
    reviewer_notes: str


def reviewer_decision_to_claim_status(
    decision: ReviewerDecision,
) -> ClaimStatus:
    """
    Convert a reviewer decision into the final claim status.
    """
    if decision == ReviewerDecision.APPROVED:
        return ClaimStatus.APPROVED

    if decision == ReviewerDecision.DENIED:
        return ClaimStatus.DENIED

    raise ValueError(
        f"Unsupported reviewer decision: {decision}"
    )


def build_manual_review_decision_index(
    decision_records: list[dict[str, Any]],
) -> dict[str, ManualReviewDecision]:
    """
    Validate and index synthetic manual-review decisions.

    Args:
        decision_records:
            Records loaded from manual_review_decisions.json.

    Returns:
        Decisions keyed by claim ID.

    Raises:
        ValueError:
            If required fields are missing, a decision is invalid,
            or the file contains duplicate decisions.
    """
    decision_index: dict[
        str,
        ManualReviewDecision,
    ] = {}

    for record in decision_records:
        claim_id = str(
            record.get(
                "claim_id",
                "",
            )
        ).strip()

        raw_decision = str(
            record.get(
                "decision",
                "",
            )
        ).strip().upper()

        reviewer_notes = str(
            record.get(
                "reviewer_notes",
                "",
            )
        ).strip()

        if not claim_id:
            raise ValueError(
                "Manual-review decisions require a claim_id."
            )

        if claim_id in decision_index:
            raise ValueError(
                "Duplicate manual-review decision found for "
                f"claim '{claim_id}'."
            )

        try:
            decision = ReviewerDecision(
                raw_decision
            )

        except ValueError as error:
            raise ValueError(
                "Manual-review decision for "
                f"claim '{claim_id}' must be "
                "APPROVED or DENIED."
            ) from error

        if not reviewer_notes:
            raise ValueError(
                "Manual-review decision for "
                f"claim '{claim_id}' requires reviewer_notes."
            )

        decision_index[claim_id] = (
            ManualReviewDecision(
                claim_id=claim_id,
                decision=decision,
                reviewer_notes=reviewer_notes,
            )
        )

    return decision_index