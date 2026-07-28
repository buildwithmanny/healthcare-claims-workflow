from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.audit_logger import insert_claim_event
from src.database import (
    count_prior_member_claims,
    enqueue_manual_review,
    enqueue_pricing_retry,
    fetch_pending_manual_review_items,
    fetch_pending_retry_queue_items,
    find_prior_duplicate_claim_id,
    get_connection,
    mark_manual_review_in_review,
    mark_retry_cancelled,
    mark_retry_exhausted,
    mark_retry_pending,
    mark_retry_succeeded,
    resolve_manual_review,
    start_retry_attempt,
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
from src.manual_review import (
    ManualReviewDecision,
    ManualReviewStatus,
    ReviewerDecision,
)
from src.pricing import (
    PricingDecision,
    PricingOutcome,
    evaluate_pricing,
)
from src.retry_manager import (
    DEFAULT_MAX_RETRIES,
    RetryStatus,
    build_retry_queue_item,
    get_overall_pricing_attempt,
    has_retry_attempts_remaining,
)
from src.state_manager import (
    ClaimStatus,
    validate_transition,
)
from src.validator import validate_claim


@dataclass(frozen=True)
class ClaimWorkflowResult:
    """
    Result returned after claim processing.
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
    retry_count: int
    retry_status: RetryStatus | None
    retry_reason: str | None
    manual_review_status: ManualReviewStatus | None
    manual_review_reason: str | None
    reviewer_notes: str | None


def transition_claim(
    cursor: Any,
    claim_id: str,
    current_status: ClaimStatus,
    new_status: ClaimStatus,
    processing_step: str,
    event_reason: str,
    retry_attempt: int | None = None,
) -> None:
    """
    Validate, persist, and audit one claim-state transition.
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
        retry_attempt=retry_attempt,
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
    retry_count: int = 0,
    retry_status: RetryStatus | None = None,
    retry_reason: str | None = None,
    manual_review_status: ManualReviewStatus | None = None,
    manual_review_reason: str | None = None,
    reviewer_notes: str | None = None,
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
        retry_count=retry_count,
        retry_status=retry_status,
        retry_reason=retry_reason,
        manual_review_status=manual_review_status,
        manual_review_reason=manual_review_reason,
        reviewer_notes=reviewer_notes,
    )


def complete_successful_pricing(
    cursor: Any,
    claim: dict[str, str],
    pricing_decision: PricingDecision,
    fraud_review_rules: FraudReviewRules,
    eligibility_reason: str | None,
    duplicate_reason: str | None,
    retry_count: int = 0,
    retry_status: RetryStatus | None = None,
    retry_attempt: int | None = None,
) -> ClaimWorkflowResult:
    """
    Complete successful pricing, fraud review, and final routing.
    """
    claim_id = claim.get(
        "claim_id",
        "",
    ).strip()

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
        processing_step=(
            "PRICING_RETRY"
            if retry_attempt is not None
            else "PRICING"
        ),
        event_reason=(
            pricing_decision.reason
        ),
        retry_attempt=retry_attempt,
    )

    prior_claim_count = count_prior_member_claims(
        cursor=cursor,
        claim=claim,
        period_days=(
            fraud_review_rules.period_days
        ),
    )

    fraud_review_decision = evaluate_fraud_review(
        claim=claim,
        rules=fraud_review_rules,
        prior_claim_count=(
            prior_claim_count
        ),
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
            retry_attempt=retry_attempt,
        )

        enqueue_manual_review(
            cursor=cursor,
            claim_id=claim_id,
            review_reason=(
                fraud_review_decision.reason
            ),
        )

        return build_result(
            claim_id=claim_id,
            final_status=ClaimStatus.MANUAL_REVIEW,
            eligibility_reason=eligibility_reason,
            duplicate_reason=duplicate_reason,
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
            retry_count=retry_count,
            retry_status=retry_status,
            retry_reason=(
                pricing_decision.reason
                if retry_attempt is not None
                else None
            ),
            manual_review_status=(
                ManualReviewStatus.PENDING
            ),
            manual_review_reason=(
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
        retry_attempt=retry_attempt,
    )

    return build_result(
        claim_id=claim_id,
        final_status=ClaimStatus.APPROVED,
        eligibility_reason=eligibility_reason,
        duplicate_reason=duplicate_reason,
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
        retry_count=retry_count,
        retry_status=retry_status,
        retry_reason=(
            pricing_decision.reason
            if retry_attempt is not None
            else None
        ),
    )


def process_claim(
    claim: dict[str, str],
    active_diagnosis_codes: set[str],
    member_index: dict[str, dict[str, str]],
    pricing_rule_index: dict[str, dict[str, Any]],
    fraud_review_rules: FraudReviewRules,
) -> ClaimWorkflowResult:
    """
    Process one claim through its initial workflow attempt.
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
                claim=claim,
                pricing_rule_index=(
                    pricing_rule_index
                ),
                pricing_attempt=1,
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

                enqueue_pricing_retry(
                    cursor=cursor,
                    claim_id=claim_id,
                    last_error=(
                        pricing_decision.reason
                    ),
                    max_retries=(
                        DEFAULT_MAX_RETRIES
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
                    retry_status=RetryStatus.PENDING,
                    retry_reason=(
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

                enqueue_manual_review(
                    cursor=cursor,
                    claim_id=claim_id,
                    review_reason=(
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
                    manual_review_status=(
                        ManualReviewStatus.PENDING
                    ),
                    manual_review_reason=(
                        pricing_decision.reason
                    ),
                )

            return complete_successful_pricing(
                cursor=cursor,
                claim=claim,
                pricing_decision=pricing_decision,
                fraud_review_rules=(
                    fraud_review_rules
                ),
                eligibility_reason=(
                    eligibility_decision.reason
                ),
                duplicate_reason=(
                    duplicate_decision.reason
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
    Process all claims through their initial workflow attempts.
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


def process_retry_queue(
    claims: list[dict[str, str]],
    initial_results: list[ClaimWorkflowResult],
    pricing_rule_index: dict[str, dict[str, Any]],
    fraud_review_rules: FraudReviewRules,
) -> dict[str, ClaimWorkflowResult]:
    """
    Process all pending pricing retry records.
    """
    claim_index = {
        claim["claim_id"].strip(): claim
        for claim in claims
    }

    initial_result_index = {
        result.claim_id: result
        for result in initial_results
    }

    retry_results: dict[
        str,
        ClaimWorkflowResult,
    ] = {}

    pending_rows = (
        fetch_pending_retry_queue_items()
    )

    for pending_row in pending_rows:
        queue_item = build_retry_queue_item(
            pending_row
        )

        claim = claim_index.get(
            queue_item.claim_id
        )

        if claim is None:
            raise RuntimeError(
                f"Retry claim '{queue_item.claim_id}' "
                "was not found in the source claim data."
            )

        initial_result = initial_result_index.get(
            queue_item.claim_id
        )

        if initial_result is None:
            raise RuntimeError(
                f"Initial result for retry claim "
                f"'{queue_item.claim_id}' was not found."
            )

        while True:
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    attempt = start_retry_attempt(
                        cursor=cursor,
                        retry_id=(
                            queue_item.retry_id
                        ),
                    )

                    retry_count = int(
                        attempt["retry_count"]
                    )

                    max_retries = int(
                        attempt["max_retries"]
                    )

                    pricing_attempt = (
                        get_overall_pricing_attempt(
                            retry_count
                        )
                    )

                    transition_claim(
                        cursor=cursor,
                        claim_id=queue_item.claim_id,
                        current_status=(
                            ClaimStatus.PRICING_RETRY
                        ),
                        new_status=ClaimStatus.PRICING,
                        processing_step="PRICING_RETRY",
                        event_reason=(
                            f"Pricing retry attempt "
                            f"{retry_count} of "
                            f"{max_retries} started."
                        ),
                        retry_attempt=retry_count,
                    )

                    pricing_decision = evaluate_pricing(
                        claim=claim,
                        pricing_rule_index=(
                            pricing_rule_index
                        ),
                        pricing_attempt=(
                            pricing_attempt
                        ),
                    )

                    if (
                        pricing_decision.outcome
                        == PricingOutcome.SUCCESS
                    ):
                        final_result = (
                            complete_successful_pricing(
                                cursor=cursor,
                                claim=claim,
                                pricing_decision=(
                                    pricing_decision
                                ),
                                fraud_review_rules=(
                                    fraud_review_rules
                                ),
                                eligibility_reason=(
                                    initial_result
                                    .eligibility_reason
                                ),
                                duplicate_reason=(
                                    initial_result
                                    .duplicate_reason
                                ),
                                retry_count=retry_count,
                                retry_status=(
                                    RetryStatus.SUCCEEDED
                                ),
                                retry_attempt=retry_count,
                            )
                        )

                        mark_retry_succeeded(
                            cursor=cursor,
                            retry_id=(
                                queue_item.retry_id
                            ),
                        )

                        retry_results[
                            queue_item.claim_id
                        ] = final_result

                        break

                    if (
                        pricing_decision.outcome
                        == PricingOutcome.PERMANENT_FAILURE
                    ):
                        transition_claim(
                            cursor=cursor,
                            claim_id=(
                                queue_item.claim_id
                            ),
                            current_status=(
                                ClaimStatus.PRICING
                            ),
                            new_status=(
                                ClaimStatus.MANUAL_REVIEW
                            ),
                            processing_step=(
                                "PRICING_RETRY"
                            ),
                            event_reason=(
                                pricing_decision.reason
                            ),
                            retry_attempt=retry_count,
                        )

                        enqueue_manual_review(
                            cursor=cursor,
                            claim_id=(
                                queue_item.claim_id
                            ),
                            review_reason=(
                                pricing_decision.reason
                            ),
                        )

                        mark_retry_cancelled(
                            cursor=cursor,
                            retry_id=(
                                queue_item.retry_id
                            ),
                            last_error=(
                                pricing_decision.reason
                            ),
                        )

                        retry_results[
                            queue_item.claim_id
                        ] = build_result(
                            claim_id=(
                                queue_item.claim_id
                            ),
                            final_status=(
                                ClaimStatus.MANUAL_REVIEW
                            ),
                            eligibility_reason=(
                                initial_result
                                .eligibility_reason
                            ),
                            duplicate_reason=(
                                initial_result
                                .duplicate_reason
                            ),
                            pricing_outcome=(
                                pricing_decision.outcome
                            ),
                            pricing_reason=(
                                pricing_decision.reason
                            ),
                            retry_count=retry_count,
                            retry_status=(
                                RetryStatus.CANCELLED
                            ),
                            retry_reason=(
                                pricing_decision.reason
                            ),
                            manual_review_status=(
                                ManualReviewStatus.PENDING
                            ),
                            manual_review_reason=(
                                pricing_decision.reason
                            ),
                        )

                        break

                    transition_claim(
                        cursor=cursor,
                        claim_id=queue_item.claim_id,
                        current_status=ClaimStatus.PRICING,
                        new_status=(
                            ClaimStatus.PRICING_RETRY
                        ),
                        processing_step="PRICING_RETRY",
                        event_reason=(
                            pricing_decision.reason
                        ),
                        retry_attempt=retry_count,
                    )

                    if has_retry_attempts_remaining(
                        retry_count=retry_count,
                        max_retries=max_retries,
                    ):
                        mark_retry_pending(
                            cursor=cursor,
                            retry_id=(
                                queue_item.retry_id
                            ),
                            last_error=(
                                pricing_decision.reason
                            ),
                        )

                        continue

                    exhausted_reason = (
                        f"Pricing retry attempts exhausted "
                        f"after {retry_count} of "
                        f"{max_retries} allowed retries. "
                        f"Final error: "
                        f"{pricing_decision.reason}"
                    )

                    transition_claim(
                        cursor=cursor,
                        claim_id=queue_item.claim_id,
                        current_status=(
                            ClaimStatus.PRICING_RETRY
                        ),
                        new_status=(
                            ClaimStatus.MANUAL_REVIEW
                        ),
                        processing_step="PRICING_RETRY",
                        event_reason=(
                            exhausted_reason
                        ),
                        retry_attempt=retry_count,
                    )

                    enqueue_manual_review(
                        cursor=cursor,
                        claim_id=queue_item.claim_id,
                        review_reason=(
                            exhausted_reason
                        ),
                    )

                    mark_retry_exhausted(
                        cursor=cursor,
                        retry_id=(
                            queue_item.retry_id
                        ),
                        last_error=(
                            pricing_decision.reason
                        ),
                    )

                    retry_results[
                        queue_item.claim_id
                    ] = build_result(
                        claim_id=queue_item.claim_id,
                        final_status=(
                            ClaimStatus.MANUAL_REVIEW
                        ),
                        eligibility_reason=(
                            initial_result
                            .eligibility_reason
                        ),
                        duplicate_reason=(
                            initial_result
                            .duplicate_reason
                        ),
                        pricing_outcome=(
                            pricing_decision.outcome
                        ),
                        pricing_reason=(
                            pricing_decision.reason
                        ),
                        retry_count=retry_count,
                        retry_status=(
                            RetryStatus.EXHAUSTED
                        ),
                        retry_reason=(
                            exhausted_reason
                        ),
                        manual_review_status=(
                            ManualReviewStatus.PENDING
                        ),
                        manual_review_reason=(
                            exhausted_reason
                        ),
                    )

                    break

    return retry_results


def process_manual_review_queue(
    current_results: list[ClaimWorkflowResult],
    decision_index: dict[
        str,
        ManualReviewDecision,
    ],
) -> dict[str, ClaimWorkflowResult]:
    """
    Process pending manual-review queue items.

    Queue items without a configured synthetic reviewer decision remain
    in PENDING status.

    Returns:
        A mapping of claim ID to the final reviewer outcome.
    """
    current_result_index = {
        result.claim_id: result
        for result in current_results
    }

    manual_review_results: dict[
        str,
        ClaimWorkflowResult,
    ] = {}

    pending_reviews = (
        fetch_pending_manual_review_items()
    )

    for review in pending_reviews:
        claim_id = str(
            review["claim_id"]
        )

        review_id = int(
            review["review_id"]
        )

        review_reason = str(
            review["review_reason"]
        )

        reviewer_decision = (
            decision_index.get(
                claim_id
            )
        )

        if reviewer_decision is None:
            continue

        current_result = (
            current_result_index.get(
                claim_id
            )
        )

        if current_result is None:
            raise RuntimeError(
                f"Current workflow result for manual-review "
                f"claim '{claim_id}' was not found."
            )

        if (
            reviewer_decision.decision
            == ReviewerDecision.APPROVED
        ):
            new_status = ClaimStatus.APPROVED

        else:
            new_status = ClaimStatus.DENIED

        event_reason = (
            f"Manual reviewer selected "
            f"{reviewer_decision.decision.value}. "
            f"Reviewer notes: "
            f"{reviewer_decision.reviewer_notes}"
        )

        retry_attempt = (
            current_result.retry_count
            if current_result.retry_count > 0
            else None
        )

        with get_connection() as connection:
            with connection.cursor() as cursor:
                mark_manual_review_in_review(
                    cursor=cursor,
                    review_id=review_id,
                )

                transition_claim(
                    cursor=cursor,
                    claim_id=claim_id,
                    current_status=(
                        ClaimStatus.MANUAL_REVIEW
                    ),
                    new_status=new_status,
                    processing_step="MANUAL_REVIEW",
                    event_reason=event_reason,
                    retry_attempt=retry_attempt,
                )

                resolve_manual_review(
                    cursor=cursor,
                    review_id=review_id,
                    decision=(
                        reviewer_decision
                        .decision
                        .value
                    ),
                    reviewer_notes=(
                        reviewer_decision
                        .reviewer_notes
                    ),
                )

        manual_review_results[
            claim_id
        ] = build_result(
            claim_id=claim_id,
            final_status=new_status,
            validation_errors=(
                current_result.validation_errors
            ),
            eligibility_reason=(
                current_result.eligibility_reason
            ),
            duplicate_reason=(
                current_result.duplicate_reason
            ),
            duplicate_of_claim_id=(
                current_result.duplicate_of_claim_id
            ),
            pricing_outcome=(
                current_result.pricing_outcome
            ),
            pricing_reason=(
                current_result.pricing_reason
            ),
            allowed_amount=(
                current_result.allowed_amount
            ),
            fraud_review_outcome=(
                current_result.fraud_review_outcome
            ),
            fraud_review_reason=(
                current_result.fraud_review_reason
            ),
            retry_count=(
                current_result.retry_count
            ),
            retry_status=(
                current_result.retry_status
            ),
            retry_reason=(
                current_result.retry_reason
            ),
            manual_review_status=(
                ManualReviewStatus(
                    reviewer_decision
                    .decision
                    .value
                )
            ),
            manual_review_reason=(
                current_result.manual_review_reason
                or review_reason
            ),
            reviewer_notes=(
                reviewer_decision.reviewer_notes
            ),
        )

    return manual_review_results