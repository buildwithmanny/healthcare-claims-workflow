from enum import StrEnum


class ClaimStatus(StrEnum):
    """
    All supported states in the healthcare claims workflow.

    Each persisted claim must have exactly one current state.
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


class InvalidStateTransitionError(ValueError):
    """
    Raised when a claim attempts an unsupported state transition.
    """


VALID_TRANSITIONS: dict[
    ClaimStatus,
    frozenset[ClaimStatus],
] = {
    ClaimStatus.RECEIVED: frozenset(
        {
            ClaimStatus.VALIDATING,
            ClaimStatus.FAILED,
        }
    ),

    ClaimStatus.VALIDATING: frozenset(
        {
            ClaimStatus.ELIGIBILITY_CHECK,
            ClaimStatus.VALIDATION_FAILED,
            ClaimStatus.FAILED,
        }
    ),

    ClaimStatus.VALIDATION_FAILED: frozenset(),

    ClaimStatus.ELIGIBILITY_CHECK: frozenset(
        {
            ClaimStatus.DUPLICATE_CHECK,
            ClaimStatus.INELIGIBLE,
            ClaimStatus.FAILED,
        }
    ),

    ClaimStatus.INELIGIBLE: frozenset(
        {
            ClaimStatus.DENIED,
        }
    ),

    ClaimStatus.DUPLICATE_CHECK: frozenset(
        {
            ClaimStatus.DUPLICATE,
            ClaimStatus.PRICING,
            ClaimStatus.FAILED,
        }
    ),

    ClaimStatus.DUPLICATE: frozenset(),

    ClaimStatus.PRICING: frozenset(
        {
            ClaimStatus.FRAUD_REVIEW,
            ClaimStatus.PRICING_RETRY,
            ClaimStatus.MANUAL_REVIEW,
            ClaimStatus.FAILED,
        }
    ),

    ClaimStatus.PRICING_RETRY: frozenset(
        {
            ClaimStatus.PRICING,
            ClaimStatus.MANUAL_REVIEW,
            ClaimStatus.FAILED,
        }
    ),

    ClaimStatus.FRAUD_REVIEW: frozenset(
        {
            ClaimStatus.APPROVED,
            ClaimStatus.DENIED,
            ClaimStatus.MANUAL_REVIEW,
            ClaimStatus.FAILED,
        }
    ),

    ClaimStatus.MANUAL_REVIEW: frozenset(
        {
            ClaimStatus.APPROVED,
            ClaimStatus.DENIED,
            ClaimStatus.FAILED,
        }
    ),

    ClaimStatus.APPROVED: frozenset(),

    ClaimStatus.DENIED: frozenset(),

    ClaimStatus.FAILED: frozenset(),
}


PROCESSING_STATES = frozenset(
    {
        ClaimStatus.RECEIVED,
        ClaimStatus.VALIDATING,
        ClaimStatus.ELIGIBILITY_CHECK,
        ClaimStatus.DUPLICATE_CHECK,
        ClaimStatus.PRICING,
        ClaimStatus.FRAUD_REVIEW,
    }
)


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


def get_allowed_transitions(
    current_status: ClaimStatus,
) -> frozenset[ClaimStatus]:
    """
    Return all legal next states for the supplied current state.
    """
    return VALID_TRANSITIONS[
        current_status
    ]


def is_valid_transition(
    current_status: ClaimStatus,
    new_status: ClaimStatus,
) -> bool:
    """
    Return whether the requested state transition is allowed.
    """
    return (
        new_status
        in get_allowed_transitions(
            current_status
        )
    )


def validate_transition(
    current_status: ClaimStatus,
    new_status: ClaimStatus,
) -> None:
    """
    Validate one requested claim-state transition.

    Raises:
        InvalidStateTransitionError:
            If the requested transition is not allowed.
    """
    if is_valid_transition(
        current_status,
        new_status,
    ):
        return

    allowed_statuses = sorted(
        status.value
        for status in get_allowed_transitions(
            current_status
        )
    )

    allowed_description = (
        ", ".join(
            allowed_statuses
        )
        if allowed_statuses
        else "none"
    )

    raise InvalidStateTransitionError(
        "Invalid claim state transition: "
        f"{current_status.value} -> "
        f"{new_status.value}. "
        "Allowed next states: "
        f"{allowed_description}."
    )


def is_terminal_state(
    status: ClaimStatus,
) -> bool:
    """
    Return whether a claim has reached a final workflow state.
    """
    return status in TERMINAL_STATES


def is_retry_state(
    status: ClaimStatus,
) -> bool:
    """
    Return whether a claim is waiting for retry processing.
    """
    return status in RETRY_STATES


def requires_manual_review(
    status: ClaimStatus,
) -> bool:
    """
    Return whether a claim requires human intervention.
    """
    return status in MANUAL_REVIEW_STATES


def validate_state_configuration() -> None:
    """
    Validate the state map when this module is imported.

    This prevents a newly added ClaimStatus from being forgotten in
    the transition map.
    """
    configured_states = set(
        VALID_TRANSITIONS
    )

    declared_states = set(
        ClaimStatus
    )

    if configured_states != declared_states:
        missing_states = (
            declared_states
            - configured_states
        )

        extra_states = (
            configured_states
            - declared_states
        )

        raise RuntimeError(
            "Claim state configuration is incomplete. "
            f"Missing states: {missing_states}. "
            f"Unexpected states: {extra_states}."
        )

    for terminal_status in TERMINAL_STATES:
        if VALID_TRANSITIONS[
            terminal_status
        ]:
            raise RuntimeError(
                f"Terminal state "
                f"'{terminal_status.value}' "
                "cannot have outgoing transitions."
            )

    for current_status, next_statuses in (
        VALID_TRANSITIONS.items()
    ):
        if current_status != ClaimStatus.RECEIVED:
            if (
                ClaimStatus.RECEIVED
                in next_statuses
            ):
                raise RuntimeError(
                    "RECEIVED can only be used as "
                    "the initial workflow state."
                )


validate_state_configuration()