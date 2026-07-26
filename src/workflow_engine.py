from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.audit_logger import insert_claim_event
from src.database import (
    count_prior_member_claims,
    find_prior_duplicate_claim_id,
    get_connection,
    update_claim_allowed_amount,
    update_claim_status,
    upsert_claim_record,
)
from src.duplicate_checker import (
    evaluate_duplicate,
)
from src.eligibility import evaluate_eligibility
from src.fraud_review import (
    FraudReviewOutcome,
    FraudReviewRules,
    evaluate_fraud_review,
)
from src.pricing import (
    PricingOutcome,
    evaluate_pricing,
)
from src.state_manager import (
    ClaimStatus,
    validate_transition,
)
from src.validator import validate_claim


@dataclass(frozen=True)
class ClaimWorkflowResult:
    """
    Result returned after Version 1 claim processing.
    """

    claim_id: str
    final_status: ClaimStatus
    validation_errors: tuple[str, ...]
    eligibility_reason: str | None
    duplicate_reason: str | None
    duplicate_of_claim_id: str | None
    pricing_outcome: PricingOutcome | None
    pricing_reason: str | None
    allowed_amount: Decimal | None
    fraud_review_outcome: FraudReviewOutcome | None
    fraud_review_reason: str | None


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

    The operation uses the caller's active transaction.

    If either the status update or audit insert fails, PostgreSQL rolls
    back both operations.
    """
    validate_transition(
        current_status,
        new_status,
    )

    update_claim_status(
        cursor=cursor,
        claim_id=claim_id,
        expected_current_status=(
            current_status.value
        ),
        new_status=new_status.value,
    )

    insert_claim_event(
        cursor=cursor,
        claim_id=claim_id,
        previous_status=current_status,
        new_status=new_status,
        processing_step=processing_step,
        event_reason=event_reason,
    )


def build_result(
    claim_id: str,
    final_status: ClaimStatus,
    validation_errors: tuple[str, ...] = (),
    eligibility_reason: str | None = None,
    duplicate_reason: str | None = None,
    duplicate_of_claim_id: str | None = None,
    pricing_outcome: PricingOutcome | None = None,
    pricing_reason: str | None = None,
    allowed_amount: Decimal | None = None,
    fraud_review_outcome: FraudReviewOutcome | None = None,
    fraud_review_reason: str | None = None,
) -> ClaimWorkflowResult:
    """
    Build a consistently structured workflow result.
    """
    return ClaimWorkflowResult(
        claim_id=claim_id,
        final_status=final_status,
        validation_errors=validation_errors,
        eligibility_reason=eligibility_reason,
        duplicate_reason=duplicate_reason,
        duplicate_of_claim_id=duplicate_of_claim_id,
        pricing_outcome=pricing_outcome,
        pricing_reason=pricing_reason,
        allowed_amount=allowed_amount,
        fraud_review_outcome=fraud_review_outcome,
        fraud_review_reason=fraud_review_reason,
    )


def process_claim(
    claim: dict[str, str],
    active_diagnosis_codes: set[str],
    member_index: dict[str, dict[str, str]],
    pricing_rule_index: dict[str, dict[str, Any]],
    fraud_review_rules: FraudReviewRules,
) -> ClaimWorkflowResult:
    """
    Process one claim through the complete Version 1 workflow.

    Happy path:

        RECEIVED
            ↓
        VALIDATING
            ↓
        ELIGIBILITY_CHECK
            ↓
        DUPLICATE_CHECK
            ↓
        PRICING
            ↓
        FRAUD_REVIEW
            ↓
        APPROVED
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

                return build_result(
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

                return build_result(
                    claim_id=claim_id,
                    final_status=ClaimStatus.DENIED,
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

            matched_claim_id = (
                find_prior_duplicate_claim_id(
                    cursor,
                    claim,
                )
            )

            duplicate_decision = evaluate_duplicate(
                claim,
                matched_claim_id,
            )

            if duplicate_decision.is_duplicate:
                transition_claim(
                    cursor=cursor,
                    claim_id=claim_id,
                    current_status=(
                        ClaimStatus.DUPLICATE_CHECK
                    ),
                    new_status=ClaimStatus.DUPLICATE,
                    processing_step="DUPLICATE_CHECK",
                    event_reason=(
                        duplicate_decision.reason
                    ),
                )

                return build_result(
                    claim_id=claim_id,
                    final_status=ClaimStatus.DUPLICATE,
                    eligibility_reason=(
                        eligibility_decision.reason
                    ),
                    duplicate_reason=(
                        duplicate_decision.reason
                    ),
                    duplicate_of_claim_id=(
                        duplicate_decision.matched_claim_id
                    ),
                )

            transition_claim(
                cursor=cursor,
                claim_id=claim_id,
                current_status=(
                    ClaimStatus.DUPLICATE_CHECK
                ),
                new_status=ClaimStatus.PRICING,
                processing_step="DUPLICATE_CHECK",
                event_reason=(
                    duplicate_decision.reason
                ),
            )

            pricing_decision = evaluate_pricing(
                claim,
                pricing_rule_index,
            )

            if (
                pricing_decision.outcome
                == PricingOutcome.TEMPORARY_FAILURE
            ):
                transition_claim(
                    cursor=cursor,
                    claim_id=claim_id,
                    current_status=ClaimStatus.PRICING,
                    new_status=ClaimStatus.PRICING_RETRY,
                    processing_step="PRICING",
                    event_reason=(
                        pricing_decision.reason
                    ),
                )

                return build_result(
                    claim_id=claim_id,
                    final_status=ClaimStatus.PRICING_RETRY,
                    eligibility_reason=(
                        eligibility_decision.reason
                    ),
                    duplicate_reason=(
                        duplicate_decision.reason
                    ),
                    pricing_outcome=(
                        pricing_decision.outcome
                    ),
                    pricing_reason=(
                        pricing_decision.reason
                    ),
                )

            if (
                pricing_decision.outcome
                == PricingOutcome.PERMANENT_FAILURE
            ):
                transition_claim(
                    cursor=cursor,
                    claim_id=claim_id,
                    current_status=ClaimStatus.PRICING,
                    new_status=ClaimStatus.MANUAL_REVIEW,
                    processing_step="PRICING",
                    event_reason=(
                        pricing_decision.reason
                    ),
                )

                return build_result(
                    claim_id=claim_id,
                    final_status=ClaimStatus.MANUAL_REVIEW,
                    eligibility_reason=(
                        eligibility_decision.reason
                    ),
                    duplicate_reason=(
                        duplicate_decision.reason
                    ),
                    pricing_outcome=(
                        pricing_decision.outcome
                    ),
                    pricing_reason=(
                        pricing_decision.reason
                    ),
                )

            if pricing_decision.allowed_amount is None:
                raise RuntimeError(
                    "Successful pricing did not return an "
                    f"allowed amount for claim '{claim_id}'."
                )

            update_claim_allowed_amount(
                cursor=cursor,
                claim_id=claim_id,
                allowed_amount=(
                    pricing_decision.allowed_amount
                ),
            )

            transition_claim(
                cursor=cursor,
                claim_id=claim_id,
                current_status=ClaimStatus.PRICING,
                new_status=ClaimStatus.FRAUD_REVIEW,
                processing_step="PRICING",
                event_reason=(
                    pricing_decision.reason
                ),
            )

            prior_claim_count = (
                count_prior_member_claims(
                    cursor=cursor,
                    claim=claim,
                    period_days=(
                        fraud_review_rules.period_days
                    ),
                )
            )

            fraud_review_decision = (
                evaluate_fraud_review(
                    claim=claim,
                    rules=fraud_review_rules,
                    prior_claim_count=(
                        prior_claim_count
                    ),
                )
            )

            if (
                fraud_review_decision.outcome
                == FraudReviewOutcome.MANUAL_REVIEW
            ):
                transition_claim(
                    cursor=cursor,
                    claim_id=claim_id,
                    current_status=ClaimStatus.FRAUD_REVIEW,
                    new_status=ClaimStatus.MANUAL_REVIEW,
                    processing_step="FRAUD_REVIEW",
                    event_reason=(
                        fraud_review_decision.reason
                    ),
                )

                return build_result(
                    claim_id=claim_id,
                    final_status=ClaimStatus.MANUAL_REVIEW,
                    eligibility_reason=(
                        eligibility_decision.reason
                    ),
                    duplicate_reason=(
                        duplicate_decision.reason
                    ),
                    pricing_outcome=(
                        pricing_decision.outcome
                    ),
                    pricing_reason=(
                        pricing_decision.reason
                    ),
                    allowed_amount=(
                        pricing_decision.allowed_amount
                    ),
                    fraud_review_outcome=(
                        fraud_review_decision.outcome
                    ),
                    fraud_review_reason=(
                        fraud_review_decision.reason
                    ),
                )

            transition_claim(
                cursor=cursor,
                claim_id=claim_id,
                current_status=ClaimStatus.FRAUD_REVIEW,
                new_status=ClaimStatus.APPROVED,
                processing_step="FRAUD_REVIEW",
                event_reason=(
                    fraud_review_decision.reason
                ),
            )

            return build_result(
                claim_id=claim_id,
                final_status=ClaimStatus.APPROVED,
                eligibility_reason=(
                    eligibility_decision.reason
                ),
                duplicate_reason=(
                    duplicate_decision.reason
                ),
                pricing_outcome=(
                    pricing_decision.outcome
                ),
                pricing_reason=(
                    pricing_decision.reason
                ),
                allowed_amount=(
                    pricing_decision.allowed_amount
                ),
                fraud_review_outcome=(
                    fraud_review_decision.outcome
                ),
                fraud_review_reason=(
                    fraud_review_decision.reason
                ),
            )


def process_claim_batch(
    claims: list[dict[str, str]],
    active_diagnosis_codes: set[str],
    member_index: dict[str, dict[str, str]],
    pricing_rule_index: dict[str, dict[str, Any]],
    fraud_review_rules: FraudReviewRules,
) -> list[ClaimWorkflowResult]:
    """
    Process all claims through the Version 1 workflow.

    Claims are processed in source-file order so later claims can be
    compared with previously processed claims in the same batch.
    """
    results: list[ClaimWorkflowResult] = []

    for claim in claims:
        result = process_claim(
            claim=claim,
            active_diagnosis_codes=(
                active_diagnosis_codes
            ),
            member_index=member_index,
            pricing_rule_index=(
                pricing_rule_index
            ),
            fraud_review_rules=(
                fraud_review_rules
            ),
        )

        results.append(
            result
        )

    return results