from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


class FraudReviewOutcome(StrEnum):
    """
    Supported fraud and business-rules review outcomes.
    """

    PASS = "PASS"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True)
class FraudReviewRules:
    """
    Validated configuration used during fraud and rules review.
    """

    high_billed_amount_threshold: Decimal
    max_claims_per_member: int
    period_days: int
    manual_review_procedure_codes: frozenset[str]


@dataclass(frozen=True)
class FraudReviewDecision:
    """
    Result of evaluating one claim against review rules.
    """

    outcome: FraudReviewOutcome
    reason: str


def parse_positive_decimal(
    value: Any,
    field_name: str,
) -> Decimal:
    """
    Parse a positive Decimal from review-rule configuration.

    Raises:
        ValueError: If the configured value is missing, invalid,
        or not greater than zero.
    """
    try:
        parsed_value = Decimal(
            str(value)
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"Review-rule field '{field_name}' must be numeric."
        ) from error

    if parsed_value <= 0:
        raise ValueError(
            f"Review-rule field '{field_name}' "
            "must be greater than zero."
        )

    return parsed_value


def parse_positive_integer(
    value: Any,
    field_name: str,
) -> int:
    """
    Parse a positive integer from review-rule configuration.

    Raises:
        ValueError: If the configured value is missing, invalid,
        or not greater than zero.
    """
    try:
        parsed_value = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"Review-rule field '{field_name}' "
            "must be an integer."
        ) from error

    if parsed_value <= 0:
        raise ValueError(
            f"Review-rule field '{field_name}' "
            "must be greater than zero."
        )

    return parsed_value


def build_fraud_review_rules(
    review_rules: dict[str, Any],
) -> FraudReviewRules:
    """
    Validate and normalize fraud-review configuration.

    Args:
        review_rules: Rules loaded from review_rules.json.

    Returns:
        A validated FraudReviewRules object.

    Raises:
        ValueError: If required rule configuration is invalid.
    """
    high_amount_rule = review_rules.get(
        "high_billed_amount",
        {},
    )

    frequency_rule = review_rules.get(
        "high_claim_frequency",
        {},
    )

    procedure_rule = review_rules.get(
        "manual_review_procedure_codes",
        {},
    )

    high_billed_amount_threshold = (
        parse_positive_decimal(
            high_amount_rule.get(
                "threshold"
            ),
            "high_billed_amount.threshold",
        )
    )

    max_claims_per_member = (
        parse_positive_integer(
            frequency_rule.get(
                "max_claims_per_member"
            ),
            (
                "high_claim_frequency."
                "max_claims_per_member"
            ),
        )
    )

    period_days = parse_positive_integer(
        frequency_rule.get(
            "period_days"
        ),
        "high_claim_frequency.period_days",
    )

    configured_codes = procedure_rule.get(
        "procedure_codes",
        [],
    )

    if not isinstance(
        configured_codes,
        list,
    ):
        raise ValueError(
            "manual_review_procedure_codes."
            "procedure_codes must be a list."
        )

    manual_review_procedure_codes = frozenset(
        str(code).strip()
        for code in configured_codes
        if str(code).strip()
    )

    return FraudReviewRules(
        high_billed_amount_threshold=(
            high_billed_amount_threshold
        ),
        max_claims_per_member=(
            max_claims_per_member
        ),
        period_days=period_days,
        manual_review_procedure_codes=(
            manual_review_procedure_codes
        ),
    )


def parse_claim_billed_amount(
    claim: dict[str, str],
) -> Decimal | None:
    """
    Parse the claim billed amount.

    Returns:
        A Decimal when valid, otherwise None.
    """
    raw_amount = claim.get(
        "billed_amount",
        "",
    ).strip()

    try:
        return Decimal(
            raw_amount
        )

    except InvalidOperation:
        return None


def evaluate_fraud_review(
    claim: dict[str, str],
    rules: FraudReviewRules,
    prior_claim_count: int,
) -> FraudReviewDecision:
    """
    Evaluate one priced claim against synthetic review rules.

    A claim enters manual review when any configured rule is triggered.

    Args:
        claim: Validated, eligible, nonduplicate, priced claim.
        rules: Validated review-rule configuration.
        prior_claim_count: Number of qualifying prior claims for the
        member during the configured time window.

    Returns:
        A FraudReviewDecision describing the workflow outcome.
    """
    review_reasons: list[str] = []

    claim_id = claim.get(
        "claim_id",
        "",
    ).strip()

    procedure_code = claim.get(
        "procedure_code",
        "",
    ).strip()

    billed_amount = parse_claim_billed_amount(
        claim
    )

    if billed_amount is None:
        review_reasons.append(
            "The billed amount could not be evaluated "
            "during fraud review."
        )

    elif (
        billed_amount
        > rules.high_billed_amount_threshold
    ):
        review_reasons.append(
            f"Billed amount ${billed_amount:,.2f} exceeds "
            "the manual-review threshold of "
            f"${rules.high_billed_amount_threshold:,.2f}."
        )

    if (
        procedure_code
        in rules.manual_review_procedure_codes
    ):
        review_reasons.append(
            f"Procedure code '{procedure_code}' is configured "
            "to require manual review."
        )

    total_claim_count = (
        prior_claim_count + 1
    )

    if (
        total_claim_count
        > rules.max_claims_per_member
    ):
        review_reasons.append(
            f"Member claim frequency reached "
            f"{total_claim_count} claims within "
            f"{rules.period_days} days, exceeding the "
            f"configured maximum of "
            f"{rules.max_claims_per_member}."
        )

    if review_reasons:
        return FraudReviewDecision(
            outcome=(
                FraudReviewOutcome.MANUAL_REVIEW
            ),
            reason=" ".join(
                review_reasons
            ),
        )

    return FraudReviewDecision(
        outcome=FraudReviewOutcome.PASS,
        reason=(
            f"Claim '{claim_id}' passed all configured "
            "fraud and business-review rules."
        ),
    )