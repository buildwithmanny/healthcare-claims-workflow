from dataclasses import dataclass
from typing import Any

from src.audit_logger import insert_claim_event
from src.database import (
    get_connection,
    update_claim_status,
    upsert_claim_record,
)
from src.eligibility import evaluate_eligibility
from src.state_manager import (
    ClaimStatus,
    validate_transition,
)
from src.validator import validate_claim


@dataclass(frozen=True)
class ClaimWorkflowResult:
    """
    Result returned after Day 4 claim processing.
    """

    claim_id: str
    final_status: ClaimStatus
    validation_errors: tuple[str, ...]
    eligibility_reason: str | None


def transition_claim(
    cursor: Any,
    claim_id: str,
    current_status: ClaimStatus,
    new_status: ClaimStatus,
    processing_step: str,
    event_reason: str,
) -> None:
    """
    Validate, persist, and audit one claim-state transition.

    Args:
        cursor: Active PostgreSQL cursor.
        claim_id: Claim being processed.
        current_status: Claim state before the transition.
        new_status: Requested next claim state.
        processing_step: Workflow step responsible for the transition.
        event_reason: Human-readable explanation for the transition.

    Raises:
        ValueError: If the state transition is not allowed.
        RuntimeError: If the claim record cannot be updated.
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


def process_claim(
    claim: dict[str, str],
    active_diagnosis_codes: set[str],
    member_index: dict[str, dict[str, str]],
) -> ClaimWorkflowResult:
    """
    Process one claim through intake, validation, and eligibility.

    Workflow:

        RECEIVED
            ↓
        VALIDATING
            ├── VALIDATION_FAILED
            ↓
        ELIGIBILITY_CHECK
            ├── INELIGIBLE
            │       ↓
            │     DENIED
            ↓
        DUPLICATE_CHECK

    Eligible claims stop at DUPLICATE_CHECK because duplicate
    detection belongs to Day 5.

    Invalid claims stop at VALIDATION_FAILED.

    Ineligible claims stop at DENIED.
    """
    claim_id = claim.get(
        "claim_id",
        "",
    ).strip()

    if not claim_id:
        raise ValueError(
            "Claim processing requires a claim_id so the "
            "claim can be persisted and audited."
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

                return ClaimWorkflowResult(
                    claim_id=claim_id,
                    final_status=(
                        ClaimStatus.VALIDATION_FAILED
                    ),
                    validation_errors=tuple(
                        validation_errors
                    ),
                    eligibility_reason=None,
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
                    "Claim passed validation and entered "
                    "eligibility processing."
                ),
            )

            eligibility_decision = evaluate_eligibility(
                claim,
                member_index,
            )

            if not eligibility_decision.is_eligible:
                transition_claim(
                    cursor=cursor,
                    claim_id=claim_id,
                    current_status=(
                        ClaimStatus.ELIGIBILITY_CHECK
                    ),
                    new_status=ClaimStatus.INELIGIBLE,
                    processing_step="ELIGIBILITY",
                    event_reason=(
                        eligibility_decision.reason
                    ),
                )

                transition_claim(
                    cursor=cursor,
                    claim_id=claim_id,
                    current_status=ClaimStatus.INELIGIBLE,
                    new_status=ClaimStatus.DENIED,
                    processing_step="ELIGIBILITY",
                    event_reason=(
                        "Claim was denied because member "
                        "eligibility requirements were not met."
                    ),
                )

                return ClaimWorkflowResult(
                    claim_id=claim_id,
                    final_status=ClaimStatus.DENIED,
                    validation_errors=(),
                    eligibility_reason=(
                        eligibility_decision.reason
                    ),
                )

            transition_claim(
                cursor=cursor,
                claim_id=claim_id,
                current_status=(
                    ClaimStatus.ELIGIBILITY_CHECK
                ),
                new_status=ClaimStatus.DUPLICATE_CHECK,
                processing_step="ELIGIBILITY",
                event_reason=(
                    eligibility_decision.reason
                ),
            )

    return ClaimWorkflowResult(
        claim_id=claim_id,
        final_status=ClaimStatus.DUPLICATE_CHECK,
        validation_errors=(),
        eligibility_reason=(
            eligibility_decision.reason
        ),
    )


def process_claim_batch(
    claims: list[dict[str, str]],
    active_diagnosis_codes: set[str],
    member_index: dict[str, dict[str, str]],
) -> list[ClaimWorkflowResult]:
    """
    Process claims through intake, validation, and eligibility.

    Each claim uses its own database transaction so one claim failure
    does not roll back successfully processed claims.
    """
    results: list[ClaimWorkflowResult] = []

    for claim in claims:
        result = process_claim(
            claim=claim,
            active_diagnosis_codes=(
                active_diagnosis_codes
            ),
            member_index=member_index,
        )

        results.append(
            result
        )

    return results