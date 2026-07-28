from dataclasses import dataclass
from typing import Any

from src.audit_logger import insert_claim_event
from src.database import (
    get_connection,
    update_claim_status,
    upsert_claim_record,
)
from src.state_manager import (
    ClaimStatus,
    is_terminal_state,
    validate_transition,
)


@dataclass(frozen=True)
class ClaimProcessingFailure:
    """
    Structured information about an unexpected claim-processing error.
    """

    claim_id: str
    error_type: str
    error_message: str
    audit_reason: str


def build_claim_processing_failure(
    claim: dict[str, Any],
    error: Exception,
) -> ClaimProcessingFailure:
    """
    Convert an unexpected exception into structured failure details.
    """
    claim_id = str(
        claim.get(
            "claim_id",
            "",
        )
    ).strip()

    if not claim_id:
        claim_id = "<missing-claim-id>"

    error_type = type(
        error
    ).__name__

    error_message = str(
        error
    ).strip()

    if not error_message:
        error_message = (
            "The exception did not include an error message."
        )

    audit_reason = (
        f"Unexpected technical failure during claim processing. "
        f"Error type: {error_type}. "
        f"Error message: {error_message}"
    )

    return ClaimProcessingFailure(
        claim_id=claim_id,
        error_type=error_type,
        error_message=error_message,
        audit_reason=audit_reason,
    )


def persist_claim_processing_failure(
    claim: dict[str, Any],
    failure: ClaimProcessingFailure,
) -> bool:
    """
    Make a best-effort attempt to store an unexpected failure.

    Behavior:

    1. Find the claim's current persisted state.
    2. Create the claim at RECEIVED when no record exists yet.
    3. Move a nonterminal claim to FAILED.
    4. Record the technical failure in claim_events.

    A persistence problem is intentionally contained and returns False.
    It does not raise another exception that would stop the batch.

    Returns:
        True when the failure was persisted successfully.
        False when persistence was not possible.
    """
    if failure.claim_id == "<missing-claim-id>":
        return False

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        current_status
                    FROM claims
                    WHERE claim_id = %s
                    FOR UPDATE;
                    """,
                    (
                        failure.claim_id,
                    ),
                )

                existing_claim = cursor.fetchone()

                if existing_claim is None:
                    upsert_claim_record(
                        cursor=cursor,
                        claim=claim,
                        current_status=(
                            ClaimStatus.RECEIVED.value
                        ),
                    )

                    insert_claim_event(
                        cursor=cursor,
                        claim_id=failure.claim_id,
                        previous_status=None,
                        new_status=ClaimStatus.RECEIVED,
                        processing_step="SYSTEM_ERROR",
                        event_reason=(
                            "Claim record was created while "
                            "handling an unexpected processing "
                            "failure."
                        ),
                    )

                    current_status = (
                        ClaimStatus.RECEIVED
                    )

                else:
                    current_status = ClaimStatus(
                        existing_claim[0]
                    )

                if current_status == ClaimStatus.FAILED:
                    return True

                if is_terminal_state(
                    current_status
                ):
                    return False

                validate_transition(
                    current_status,
                    ClaimStatus.FAILED,
                )

                update_claim_status(
                    cursor=cursor,
                    claim_id=failure.claim_id,
                    expected_current_status=(
                        current_status.value
                    ),
                    new_status=(
                        ClaimStatus.FAILED.value
                    ),
                )

                insert_claim_event(
                    cursor=cursor,
                    claim_id=failure.claim_id,
                    previous_status=current_status,
                    new_status=ClaimStatus.FAILED,
                    processing_step="SYSTEM_ERROR",
                    event_reason=(
                        failure.audit_reason
                    ),
                )

        return True

    except Exception:
        return False