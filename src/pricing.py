from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


class PricingOutcome(StrEnum):
    """
    Supported outcomes from the pricing step.
    """

    SUCCESS = "SUCCESS"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"


@dataclass(frozen=True)
class PricingDecision:
    """
    Result of evaluating one claim against the pricing rules.
    """

    outcome: PricingOutcome
    procedure_code: str
    allowed_amount: Decimal | None
    pricing_method: str | None
    pricing_attempt: int
    reason: str


def build_pricing_rule_index(
    pricing_records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Build a pricing-rule lookup keyed by procedure code.

    Raises:
        ValueError:
            If a rule is missing a procedure code or duplicate
            procedure-code rules exist.
    """
    pricing_rule_index: dict[str, dict[str, Any]] = {}

    for rule in pricing_records:
        procedure_code = str(
            rule.get(
                "procedure_code",
                "",
            )
        ).strip()

        if not procedure_code:
            raise ValueError(
                "Pricing reference data contains a rule "
                "without a procedure_code."
            )

        if procedure_code in pricing_rule_index:
            raise ValueError(
                "Pricing reference data contains duplicate "
                f"rules for procedure_code '{procedure_code}'."
            )

        pricing_rule_index[procedure_code] = rule

    return pricing_rule_index


def parse_allowed_amount(
    configured_amount: Any,
) -> Decimal | None:
    """
    Parse a positive configured allowed amount.
    """
    try:
        allowed_amount = Decimal(
            str(configured_amount)
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None

    if allowed_amount <= 0:
        return None

    return allowed_amount


def parse_temporary_failure_count(
    configured_value: Any,
) -> int | None:
    """
    Parse a nonnegative temporary-failure count.

    Returns:
        A nonnegative integer when valid, otherwise None.
    """
    try:
        temporary_failure_count = int(
            configured_value
        )

    except (
        TypeError,
        ValueError,
    ):
        return None

    if temporary_failure_count < 0:
        return None

    return temporary_failure_count


def evaluate_pricing(
    claim: dict[str, str],
    pricing_rule_index: dict[str, dict[str, Any]],
    pricing_attempt: int = 1,
) -> PricingDecision:
    """
    Evaluate pricing for one claim.

    Outcomes:

    SUCCESS:
        The rule exists, configuration is valid, and the simulated
        service succeeds on the current attempt.

    TEMPORARY_FAILURE:
        The rule exists, but the simulated service is configured to
        fail on the current attempt.

    PERMANENT_FAILURE:
        The pricing rule is missing or contains unusable configuration.

    Args:
        claim: Validated, eligible, nonduplicate claim.
        pricing_rule_index: Rules keyed by procedure code.
        pricing_attempt: Overall pricing attempt number. The initial
        attempt is 1. The first retry is attempt 2.

    Returns:
        A structured PricingDecision.
    """
    if pricing_attempt <= 0:
        raise ValueError(
            "pricing_attempt must be greater than zero."
        )

    procedure_code = claim.get(
        "procedure_code",
        "",
    ).strip()

    rule = pricing_rule_index.get(
        procedure_code
    )

    if rule is None:
        return PricingDecision(
            outcome=PricingOutcome.PERMANENT_FAILURE,
            procedure_code=procedure_code,
            allowed_amount=None,
            pricing_method=None,
            pricing_attempt=pricing_attempt,
            reason=(
                "Permanent pricing failure: no pricing rule "
                f"was configured for procedure code "
                f"'{procedure_code}'."
            ),
        )

    pricing_method = str(
        rule.get(
            "pricing_method",
            "",
        )
    ).strip()

    if not pricing_method:
        return PricingDecision(
            outcome=PricingOutcome.PERMANENT_FAILURE,
            procedure_code=procedure_code,
            allowed_amount=None,
            pricing_method=None,
            pricing_attempt=pricing_attempt,
            reason=(
                "Permanent pricing failure: pricing_method "
                f"was not configured for procedure code "
                f"'{procedure_code}'."
            ),
        )

    temporary_failure_count = (
        parse_temporary_failure_count(
            rule.get(
                "temporary_failures_before_success",
                0,
            )
        )
    )

    if temporary_failure_count is None:
        return PricingDecision(
            outcome=PricingOutcome.PERMANENT_FAILURE,
            procedure_code=procedure_code,
            allowed_amount=None,
            pricing_method=pricing_method,
            pricing_attempt=pricing_attempt,
            reason=(
                "Permanent pricing failure: "
                "temporary_failures_before_success must be "
                f"a nonnegative integer for procedure code "
                f"'{procedure_code}'."
            ),
        )

    if pricing_attempt <= temporary_failure_count:
        return PricingDecision(
            outcome=PricingOutcome.TEMPORARY_FAILURE,
            procedure_code=procedure_code,
            allowed_amount=None,
            pricing_method=pricing_method,
            pricing_attempt=pricing_attempt,
            reason=(
                "Temporary pricing failure: simulated "
                "pricing-service timeout for procedure code "
                f"'{procedure_code}' on pricing attempt "
                f"{pricing_attempt}."
            ),
        )

    allowed_amount = parse_allowed_amount(
        rule.get(
            "allowed_amount"
        )
    )

    if allowed_amount is None:
        return PricingDecision(
            outcome=PricingOutcome.PERMANENT_FAILURE,
            procedure_code=procedure_code,
            allowed_amount=None,
            pricing_method=pricing_method,
            pricing_attempt=pricing_attempt,
            reason=(
                "Permanent pricing failure: the configured "
                f"allowed amount for procedure code "
                f"'{procedure_code}' was missing, invalid, "
                "or not greater than zero."
            ),
        )

    return PricingDecision(
        outcome=PricingOutcome.SUCCESS,
        procedure_code=procedure_code,
        allowed_amount=allowed_amount,
        pricing_method=pricing_method,
        pricing_attempt=pricing_attempt,
        reason=(
            f"Pricing completed successfully for procedure "
            f"code '{procedure_code}' on pricing attempt "
            f"{pricing_attempt} using pricing method "
            f"'{pricing_method}'. Allowed amount: "
            f"${allowed_amount:,.2f}."
        ),
    )