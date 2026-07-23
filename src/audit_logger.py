from typing import Any

from src.state_manager import ClaimStatus


def insert_claim_event(
    cursor: Any,
    claim_id: str,
    previous_status: ClaimStatus | None,
    new_status: ClaimStatus,
    processing_step: str,
    event_reason: str | None = None,
    retry_attempt: int | None = None,
) -> None:
    """
    Insert one workflow event into the audit history.

    This function uses the caller's active database cursor so the
    status update and audit event can be committed together.

    Args:
        cursor: Active PostgreSQL cursor.
        claim_id: Claim being processed.
        previous_status: State before the event, or None for intake.
        new_status: State after the event.
        processing_step: Workflow step responsible for the change.
        event_reason: Explanation for the transition.
        retry_attempt: Retry number when applicable.
    """
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
        );
        """,
        (
            claim_id,
            (
                previous_status.value
                if previous_status is not None
                else None
            ),
            new_status.value,
            processing_step,
            event_reason,
            retry_attempt,
        ),
    )