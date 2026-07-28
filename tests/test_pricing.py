from src.pricing import (
    PricingOutcome,
    evaluate_pricing,
)


def test_pricing_success_assigns_allowed_amount(
    valid_claim,
    pricing_rule_index,
):
    decision = evaluate_pricing(
        claim=valid_claim,
        pricing_rule_index=pricing_rule_index,
        pricing_attempt=1,
    )

    assert decision.outcome == PricingOutcome.SUCCESS
    assert str(
        decision.allowed_amount
    ) == "150.0"


def test_pricing_timeout_is_temporary_failure(
    valid_claim,
    pricing_rule_index,
):
    claim = valid_claim.copy()
    claim["procedure_code"] = "PROC1005"

    decision = evaluate_pricing(
        claim=claim,
        pricing_rule_index=pricing_rule_index,
        pricing_attempt=1,
    )

    assert (
        decision.outcome
        == PricingOutcome.TEMPORARY_FAILURE
    )

    assert "timeout" in decision.reason


def test_pricing_retry_can_succeed(
    valid_claim,
    pricing_rule_index,
):
    claim = valid_claim.copy()
    claim["procedure_code"] = "PROC1005"

    decision = evaluate_pricing(
        claim=claim,
        pricing_rule_index=pricing_rule_index,
        pricing_attempt=2,
    )

    assert decision.outcome == PricingOutcome.SUCCESS
    assert str(
        decision.allowed_amount
    ) == "500.0"


def test_missing_pricing_rule_is_permanent_failure(
    valid_claim,
    pricing_rule_index,
):
    claim = valid_claim.copy()
    claim["procedure_code"] = "PROC9999"

    decision = evaluate_pricing(
        claim=claim,
        pricing_rule_index=pricing_rule_index,
        pricing_attempt=1,
    )

    assert (
        decision.outcome
        == PricingOutcome.PERMANENT_FAILURE
    )

    assert decision.allowed_amount is None