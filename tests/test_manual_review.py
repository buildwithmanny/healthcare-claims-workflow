import pytest

from src.manual_review import (
    ReviewerDecision,
    build_manual_review_decision_index,
    reviewer_decision_to_claim_status,
)
from src.state_manager import ClaimStatus


def test_manual_review_approval_routes_to_approved():
    status = reviewer_decision_to_claim_status(
        ReviewerDecision.APPROVED
    )

    assert status == ClaimStatus.APPROVED


def test_manual_review_denial_routes_to_denied():
    status = reviewer_decision_to_claim_status(
        ReviewerDecision.DENIED
    )

    assert status == ClaimStatus.DENIED


def test_manual_review_decision_requires_notes():
    with pytest.raises(
        ValueError,
    ):
        build_manual_review_decision_index(
            [
                {
                    "claim_id": "CLM001",
                    "decision": "APPROVED",
                    "reviewer_notes": "",
                }
            ]
        )


def test_manual_review_decision_index_is_keyed_by_claim():
    decision_index = (
        build_manual_review_decision_index(
            [
                {
                    "claim_id": "CLM001",
                    "decision": "APPROVED",
                    "reviewer_notes": (
                        "Synthetic review completed."
                    ),
                }
            ]
        )
    )

    assert "CLM001" in decision_index

    assert (
        decision_index["CLM001"].decision
        == ReviewerDecision.APPROVED
    )