import pytest

from src.state_manager import (
    ClaimStatus,
    InvalidStateTransitionError,
    get_allowed_transitions,
    is_terminal_state,
    validate_transition,
)


@pytest.mark.parametrize(
    (
        "current_status",
        "new_status",
    ),
    [
        (
            ClaimStatus.RECEIVED,
            ClaimStatus.VALIDATING,
        ),
        (
            ClaimStatus.VALIDATING,
            ClaimStatus.ELIGIBILITY_CHECK,
        ),
        (
            ClaimStatus.ELIGIBILITY_CHECK,
            ClaimStatus.DUPLICATE_CHECK,
        ),
        (
            ClaimStatus.DUPLICATE_CHECK,
            ClaimStatus.PRICING,
        ),
        (
            ClaimStatus.PRICING,
            ClaimStatus.FRAUD_REVIEW,
        ),
        (
            ClaimStatus.FRAUD_REVIEW,
            ClaimStatus.APPROVED,
        ),
        (
            ClaimStatus.MANUAL_REVIEW,
            ClaimStatus.DENIED,
        ),
    ],
)
def test_valid_state_transitions(
    current_status,
    new_status,
):
    validate_transition(
        current_status,
        new_status,
    )


def test_invalid_state_transition_is_blocked():
    with pytest.raises(
        InvalidStateTransitionError,
    ):
        validate_transition(
            ClaimStatus.VALIDATION_FAILED,
            ClaimStatus.PRICING,
        )


def test_approved_claim_cannot_move_again():
    assert is_terminal_state(
        ClaimStatus.APPROVED
    ) is True

    assert get_allowed_transitions(
        ClaimStatus.APPROVED
    ) == frozenset()


def test_duplicate_claim_cannot_move_to_pricing():
    with pytest.raises(
        InvalidStateTransitionError,
    ):
        validate_transition(
            ClaimStatus.DUPLICATE,
            ClaimStatus.PRICING,
        )