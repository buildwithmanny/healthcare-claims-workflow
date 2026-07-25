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
    reason: str


def build_pricing_rule_index(
    pricing_records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Build a pricing-rule lookup keyed by procedure code.

    Args:
        pricing_records: Pricing records loaded from JSON.

    Returns:
        A dictionary mapping each procedure code to its rule.

    Raises:
        ValueError: If a rule is missing a procedure code or if
        duplicate procedure-code rules exist.
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


def should_simulate_timeout(
    rule: dict[str, Any],
) -> bool:
    """
    Return whether a pricing rule should simulate a timeout.

    The JSON value may be represented as either a Boolean or a string.
    """
    configured_value = rule.get(
        "simulate_timeout",
        False,
    )

    if isinstance(
        configured_value,
        bool,
    ):
        return configured_value

    if isinstance(
        configured_value,
        str,
    ):
        return (
            configured_value.strip().lower()
            == "true"
        )

    return False


def parse_allowed_amount(
    configured_amount: Any,
) -> Decimal | None:
    """
    Parse a configured pricing amount.

    Args:
        configured_amount: Value loaded from the pricing rule.

    Returns:
        A positive Decimal when valid, otherwise None.
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


def evaluate_pricing(
    claim: dict[str, str],
    pricing_rule_index: dict[str, dict[str, Any]],
) -> PricingDecision:
    """
    Evaluate pricing for one claim.

    Outcomes:

    SUCCESS:
        The rule exists and contains a valid allowed amount.

    TEMPORARY_FAILURE:
        The rule exists, but a timeout is intentionally simulated.

    PERMANENT_FAILURE:
        The rule is missing or contains unusable configuration.

    Args:
        claim: Validated, eligible, nonduplicate claim.
        pricing_rule_index: Rules keyed by procedure code.

    Returns:
        A structured PricingDecision.
    """
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

    if should_simulate_timeout(
        rule
    ):
        return PricingDecision(
            outcome=PricingOutcome.TEMPORARY_FAILURE,
            procedure_code=procedure_code,
            allowed_amount=None,
            pricing_method=(
                pricing_method or None
            ),
            reason=(
                "Temporary pricing failure: a simulated "
                "pricing-service timeout occurred for "
                f"procedure code '{procedure_code}'."
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
            pricing_method=(
                pricing_method or None
            ),
            reason=(
                "Permanent pricing failure: the configured "
                f"allowed amount for procedure code "
                f"'{procedure_code}' was missing, invalid, "
                "or not greater than zero."
            ),
        )

    if not pricing_method:
        return PricingDecision(
            outcome=PricingOutcome.PERMANENT_FAILURE,
            procedure_code=procedure_code,
            allowed_amount=None,
            pricing_method=None,
            reason=(
                "Permanent pricing failure: pricing_method "
                f"was not configured for procedure code "
                f"'{procedure_code}'."
            ),
        )

    return PricingDecision(
        outcome=PricingOutcome.SUCCESS,
        procedure_code=procedure_code,
        allowed_amount=allowed_amount,
        pricing_method=pricing_method,
        reason=(
            f"Pricing completed successfully for procedure "
            f"code '{procedure_code}' using pricing method "
            f"'{pricing_method}'. Allowed amount: "
            f"${allowed_amount:,.2f}."
        ),
    )