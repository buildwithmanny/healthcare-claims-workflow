from typing import Any

from src.state_manager import (
    ClaimStatus,
    validate_transition,
)


def insert_claim_event(
    cursor: Any,
    claim_id: str,
    previous_status: ClaimStatus | None,
    new_status: ClaimStatus,
    processing_step: str,
    event_reason: str,
    retry_attempt: int | None = None,
) -> int:
    """
    Insert one valid workflow event into claim_events.

    The caller supplies an active database cursor so the current-state
    update and audit event can be committed in the same transaction.

    Args:
        cursor: Active PostgreSQL cursor.
        claim_id: Claim being processed.
        previous_status: State before the event. None is permitted only
        for the initial RECEIVED event.
        new_status: State after the event.
        processing_step: Workflow step responsible for the event.
        event_reason: Explanation for why the status changed.
        retry_attempt: Retry number when applicable.

    Returns:
        The generated event ID.

    Raises:
        ValueError:
            If required audit information is missing.
        InvalidStateTransitionError:
            If a noninitial transition is invalid.
    """
    cleaned_claim_id = claim_id.strip()
    cleaned_processing_step = (
        processing_step.strip()
    )
    cleaned_event_reason = (
        event_reason.strip()
    )

    if not cleaned_claim_id:
        raise ValueError(
            "Audit events require a claim_id."
        )

    if not cleaned_processing_step:
        raise ValueError(
            "Audit events require a processing_step."
        )

    if not cleaned_event_reason:
        raise ValueError(
            "Audit events require an event_reason."
        )

    if (
        retry_attempt is not None
        and retry_attempt < 0
    ):
        raise ValueError(
            "retry_attempt cannot be negative."
        )

    if previous_status is None:
        if new_status != ClaimStatus.RECEIVED:
            raise ValueError(
                "The initial claim event must move "
                "from no prior state to RECEIVED."
            )

    else:
        validate_transition(
            previous_status,
            new_status,
        )

    cursor.execute(
        """
        INSERT INTO claim_events (
            claim_id,
            previous_status,
            new_status,
            processing_step,
            event_reason,
            retry_attempt
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        RETURNING event_id;
        """,
        (
            cleaned_claim_id,
            (
                previous_status.value
                if previous_status is not None
                else None
            ),
            new_status.value,
            cleaned_processing_step,
            cleaned_event_reason,
            retry_attempt,
        ),
    )

    result = cursor.fetchone()

    if result is None:
        raise RuntimeError(
            "PostgreSQL did not return an event ID."
        )

    return int(
        result[0]
    )