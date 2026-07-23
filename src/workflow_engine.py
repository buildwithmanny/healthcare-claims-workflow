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
    validate_transition,
)
from src.validator import validate_claim


@dataclass(frozen=True)
class ClaimIntakeResult:
    """
    Result returned after claim intake and validation.
    """

    claim_id: str
    final_status: ClaimStatus
    validation_errors: tuple[str, ...]


def transition_claim(
    cursor: Any,
    claim_id: str,
    current_status: ClaimStatus,
    new_status: ClaimStatus,
    processing_step: str,
    event_reason: str,
) -> None:
    """
    Validate, persist, and audit one state transition.

    Raises:
        ValueError: If the transition is not allowed.
        RuntimeError: If the claim cannot be updated.
    """
    validate_transition(
        current_status,
        new_status,
    )

    update_claim_status(
        cursor,
        claim_id,
        new_status.value,
    )

    insert_claim_event(
        cursor=cursor,
        claim_id=claim_id,
        previous_status=current_status,
        new_status=new_status,
        processing_step=processing_step,
        event_reason=event_reason,
    )


def process_claim_intake(
    claim: dict[str, str],
    active_diagnosis_codes: set[str],
) -> ClaimIntakeResult:
    """
    Process one claim through intake and validation.

    Workflow:

        RECEIVED
            ↓
        VALIDATING
            ├── VALIDATION_FAILED
            └── ELIGIBILITY_CHECK

    Valid claims stop at ELIGIBILITY_CHECK because eligibility logic
    belongs to Day 4.

    Invalid claims stop at VALIDATION_FAILED.
    """
    claim_id = claim.get(
        "claim_id",
        "",
    ).strip()

    if not claim_id:
        raise ValueError(
            "Day 3 intake requires a source claim_id "
            "so the claim can be persisted and audited."
        )

    validation_errors = validate_claim(
        claim,
        active_diagnosis_codes,
    )

    with get_connection() as connection:
        with connection.cursor() as cursor:
            upsert_claim_record(
                cursor,
                claim,
                ClaimStatus.RECEIVED.value,
            )

            insert_claim_event(
                cursor=cursor,
                claim_id=claim_id,
                previous_status=None,
                new_status=ClaimStatus.RECEIVED,
                processing_step="CLAIM_INTAKE",
                event_reason=(
                    "Claim was loaded into the workflow."
                ),
            )

            transition_claim(
                cursor=cursor,
                claim_id=claim_id,
                current_status=ClaimStatus.RECEIVED,
                new_status=ClaimStatus.VALIDATING,
                processing_step="VALIDATION",
                event_reason=(
                    "Claim validation started."
                ),
            )

            if validation_errors:
                failure_reason = "; ".join(
                    validation_errors
                )

                transition_claim(
                    cursor=cursor,
                    claim_id=claim_id,
                    current_status=ClaimStatus.VALIDATING,
                    new_status=(
                        ClaimStatus.VALIDATION_FAILED
                    ),
                    processing_step="VALIDATION",
                    event_reason=failure_reason,
                )

                return ClaimIntakeResult(
                    claim_id=claim_id,
                    final_status=(
                        ClaimStatus.VALIDATION_FAILED
                    ),
                    validation_errors=tuple(
                        validation_errors
                    ),
                )

            transition_claim(
                cursor=cursor,
                claim_id=claim_id,
                current_status=ClaimStatus.VALIDATING,
                new_status=(
                    ClaimStatus.ELIGIBILITY_CHECK
                ),
                processing_step="VALIDATION",
                event_reason=(
                    "Claim passed validation and is ready "
                    "for eligibility processing."
                ),
            )

    return ClaimIntakeResult(
        claim_id=claim_id,
        final_status=ClaimStatus.ELIGIBILITY_CHECK,
        validation_errors=(),
    )


def process_claim_batch(
    claims: list[dict[str, str]],
    active_diagnosis_codes: set[str],
) -> list[ClaimIntakeResult]:
    """
    Process a batch of claims through intake and validation.

    Each claim is handled independently so one invalid claim does not
    stop the remaining batch.
    """
    results: list[ClaimIntakeResult] = []

    for claim in claims:
        result = process_claim_intake(
            claim,
            active_diagnosis_codes,
        )

        results.append(result)

    return results