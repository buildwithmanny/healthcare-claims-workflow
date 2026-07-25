from dataclasses import dataclass


DUPLICATE_FIELDS = (
    "member_id",
    "provider_id",
    "procedure_code",
    "service_date",
)


@dataclass(frozen=True)
class DuplicateDecision:
    """
    Result of evaluating one claim for duplication.
    """

    is_duplicate: bool
    matched_claim_id: str | None
    reason: str


def build_duplicate_signature(
    claim: dict[str, str],
) -> tuple[str, str, str, str]:
    """
    Build the composite value used for duplicate comparison.

    The initial duplicate rule compares:

    - member_id
    - provider_id
    - procedure_code
    - service_date

    Args:
        claim: Validated and eligible claim record.

    Returns:
        A normalized four-value duplicate signature.
    """
    return (
        claim.get(
            "member_id",
            "",
        ).strip(),
        claim.get(
            "provider_id",
            "",
        ).strip(),
        claim.get(
            "procedure_code",
            "",
        ).strip(),
        claim.get(
            "service_date",
            "",
        ).strip(),
    )


def evaluate_duplicate(
    claim: dict[str, str],
    matched_claim_id: str | None,
) -> DuplicateDecision:
    """
    Convert a duplicate lookup result into a workflow decision.

    Args:
        claim: Claim currently being evaluated.
        matched_claim_id: Previously processed matching claim, if one
        was found.

    Returns:
        A DuplicateDecision describing whether processing should stop.
    """
    member_id, provider_id, procedure_code, service_date = (
        build_duplicate_signature(
            claim
        )
    )

    if matched_claim_id is not None:
        return DuplicateDecision(
            is_duplicate=True,
            matched_claim_id=matched_claim_id,
            reason=(
                f"Claim matched prior claim '{matched_claim_id}' "
                "using member_id, provider_id, procedure_code, "
                "and service_date. "
                f"Comparison values: member_id={member_id}, "
                f"provider_id={provider_id}, "
                f"procedure_code={procedure_code}, "
                f"service_date={service_date}."
            ),
        )

    return DuplicateDecision(
        is_duplicate=False,
        matched_claim_id=None,
        reason=(
            "No previously processed eligible claim matched "
            "member_id, provider_id, procedure_code, and "
            "service_date. "
            f"Comparison values: member_id={member_id}, "
            f"provider_id={provider_id}, "
            f"procedure_code={procedure_code}, "
            f"service_date={service_date}."
        ),
    )