from src.duplicate_checker import (
    evaluate_duplicate,
)
from src.eligibility import (
    build_member_index,
    evaluate_eligibility,
)
from src.fraud_review import (
    FraudReviewOutcome,
    evaluate_fraud_review,
)
from src.pricing import (
    PricingOutcome,
    evaluate_pricing,
)
from src.validator import validate_claim


def test_valid_claim_passes_core_processing_modules(
    valid_claim,
    active_diagnosis_codes,
    member_records,
    pricing_rule_index,
    fraud_review_rules,
):
    """
    Confirm the core happy-path decisions without requiring PostgreSQL.
    """
    validation_errors = validate_claim(
        valid_claim,
        active_diagnosis_codes,
    )

    assert validation_errors == []

    member_index = build_member_index(
        member_records
    )

    eligibility_decision = evaluate_eligibility(
        valid_claim,
        member_index,
    )

    assert eligibility_decision.is_eligible is True

    duplicate_decision = evaluate_duplicate(
        valid_claim,
        matched_claim_id=None,
    )

    assert duplicate_decision.is_duplicate is False

    pricing_decision = evaluate_pricing(
        claim=valid_claim,
        pricing_rule_index=pricing_rule_index,
        pricing_attempt=1,
    )

    assert (
        pricing_decision.outcome
        == PricingOutcome.SUCCESS
    )

    assert str(
        pricing_decision.allowed_amount
    ) == "150.0"

    fraud_decision = evaluate_fraud_review(
        claim=valid_claim,
        rules=fraud_review_rules,
        prior_claim_count=0,
    )

    assert (
        fraud_decision.outcome
        == FraudReviewOutcome.PASS
    )