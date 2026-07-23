from enum import StrEnum


class ClaimStatus(StrEnum):
    """
    All supported states in the healthcare claims workflow.

    Each claim must have exactly one current state.
    """

    RECEIVED = "RECEIVED"

    VALIDATING = "VALIDATING"
    VALIDATION_FAILED = "VALIDATION_FAILED"

    ELIGIBILITY_CHECK = "ELIGIBILITY_CHECK"
    INELIGIBLE = "INELIGIBLE"

    DUPLICATE_CHECK = "DUPLICATE_CHECK"
    DUPLICATE = "DUPLICATE"

    PRICING = "PRICING"
    PRICING_RETRY = "PRICING_RETRY"

    FRAUD_REVIEW = "FRAUD_REVIEW"
    MANUAL_REVIEW = "MANUAL_REVIEW"

    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FAILED = "FAILED"


VALID_TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    ClaimStatus.RECEIVED: {
        ClaimStatus.VALIDATING,
        ClaimStatus.FAILED,
    },

    ClaimStatus.VALIDATING: {
        ClaimStatus.ELIGIBILITY_CHECK,
        ClaimStatus.VALIDATION_FAILED,
        ClaimStatus.FAILED,
    },

    ClaimStatus.VALIDATION_FAILED: set(),

    ClaimStatus.ELIGIBILITY_CHECK: {
        ClaimStatus.DUPLICATE_CHECK,
        ClaimStatus.INELIGIBLE,
        ClaimStatus.FAILED,
    },

    ClaimStatus.INELIGIBLE: {
        ClaimStatus.DENIED,
    },

    ClaimStatus.DUPLICATE_CHECK: {
        ClaimStatus.DUPLICATE,
        ClaimStatus.PRICING,
        ClaimStatus.FAILED,
    },

    ClaimStatus.DUPLICATE: set(),

    ClaimStatus.PRICING: {
        ClaimStatus.FRAUD_REVIEW,
        ClaimStatus.PRICING_RETRY,
        ClaimStatus.MANUAL_REVIEW,
        ClaimStatus.FAILED,
    },

    ClaimStatus.PRICING_RETRY: {
        ClaimStatus.PRICING,
        ClaimStatus.MANUAL_REVIEW,
        ClaimStatus.FAILED,
    },

    ClaimStatus.FRAUD_REVIEW: {
        ClaimStatus.APPROVED,
        ClaimStatus.DENIED,
        ClaimStatus.MANUAL_REVIEW,
        ClaimStatus.FAILED,
    },

    ClaimStatus.MANUAL_REVIEW: {
        ClaimStatus.APPROVED,
        ClaimStatus.DENIED,
        ClaimStatus.FAILED,
    },

    ClaimStatus.APPROVED: set(),

    ClaimStatus.DENIED: set(),

    ClaimStatus.FAILED: set(),
}


TERMINAL_STATES = frozenset(
    {
        ClaimStatus.VALIDATION_FAILED,
        ClaimStatus.DUPLICATE,
        ClaimStatus.APPROVED,
        ClaimStatus.DENIED,
        ClaimStatus.FAILED,
    }
)


RETRY_STATES = frozenset(
    {
        ClaimStatus.PRICING_RETRY,
    }
)


MANUAL_REVIEW_STATES = frozenset(
    {
        ClaimStatus.MANUAL_REVIEW,
    }
)


def is_valid_transition(
    current_status: ClaimStatus,
    new_status: ClaimStatus,
) -> bool:
    """
    Return True when a workflow transition is allowed.

    Args:
        current_status: The claim's current workflow state.
        new_status: The requested next workflow state.

    Returns:
        True if the transition is valid, otherwise False.
    """
    allowed_transitions = VALID_TRANSITIONS.get(
        current_status,
        set(),
    )

    return new_status in allowed_transitions


def validate_transition(
    current_status: ClaimStatus,
    new_status: ClaimStatus,
) -> None:
    """
    Validate a requested workflow transition.

    Raises:
        ValueError: If the requested transition is not allowed.
    """
    if not is_valid_transition(
        current_status,
        new_status,
    ):
        raise ValueError(
            "Invalid claim state transition: "
            f"{current_status.value} -> {new_status.value}"
        )


def get_allowed_transitions(
    current_status: ClaimStatus,
) -> set[ClaimStatus]:
    """
    Return all states that can legally follow the current state.

    Args:
        current_status: The claim's current workflow state.

    Returns:
        A copy of the set of allowed next states.
    """
    return VALID_TRANSITIONS.get(
        current_status,
        set(),
    ).copy()


def is_terminal_state(
    status: ClaimStatus,
) -> bool:
    """
    Return True when the claim has reached a final workflow state.
    """
    return status in TERMINAL_STATES