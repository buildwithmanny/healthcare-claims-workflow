from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class EligibilityDecision:
    """
    Result of evaluating one claim for member eligibility.
    """

    is_eligible: bool
    reason: str


def build_member_index(
    member_records: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    """
    Build a lookup dictionary keyed by member ID.

    Args:
        member_records: Member records loaded from members.csv.

    Returns:
        A dictionary where each member ID maps to one member record.

    Raises:
        ValueError: If a member record is missing a member ID or if
        duplicate member IDs exist in the reference data.
    """
    member_index: dict[str, dict[str, str]] = {}

    for member in member_records:
        member_id = member.get(
            "member_id",
            "",
        ).strip()

        if not member_id:
            raise ValueError(
                "Member reference data contains a record "
                "without a member_id."
            )

        if member_id in member_index:
            raise ValueError(
                "Member reference data contains a duplicate "
                f"member_id: {member_id}"
            )

        member_index[member_id] = member

    return member_index


def parse_reference_date(
    value: str,
) -> date | None:
    """
    Parse an ISO-formatted reference date.

    Args:
        value: Date value expected in YYYY-MM-DD format.

    Returns:
        A date object when valid, otherwise None.
    """
    cleaned_value = value.strip()

    if not cleaned_value:
        return None

    try:
        return date.fromisoformat(
            cleaned_value
        )

    except ValueError:
        return None


def evaluate_eligibility(
    claim: dict[str, str],
    member_index: dict[str, dict[str, str]],
) -> EligibilityDecision:
    """
    Evaluate whether a member was eligible on the claim service date.

    Eligibility requirements:

    1. The member must exist.
    2. The member status must be ACTIVE.
    3. Coverage dates must be valid.
    4. The service date must fall within the coverage period.

    Args:
        claim: Validated claim record.
        member_index: Member records indexed by member ID.

    Returns:
        An EligibilityDecision containing the outcome and reason.
    """
    member_id = claim.get(
        "member_id",
        "",
    ).strip()

    member = member_index.get(
        member_id
    )

    if member is None:
        return EligibilityDecision(
            is_eligible=False,
            reason=(
                f"Member '{member_id}' was not found "
                "in the member reference data."
            ),
        )

    member_status = member.get(
        "member_status",
        "",
    ).strip().upper()

    if member_status != "ACTIVE":
        return EligibilityDecision(
            is_eligible=False,
            reason=(
                f"Member '{member_id}' is not active. "
                f"Current member status: "
                f"{member_status or 'MISSING'}."
            ),
        )

    service_date = parse_reference_date(
        claim.get(
            "service_date",
            "",
        )
    )

    if service_date is None:
        return EligibilityDecision(
            is_eligible=False,
            reason=(
                "The claim service date could not be "
                "evaluated for eligibility."
            ),
        )

    coverage_start = parse_reference_date(
        member.get(
            "coverage_start",
            "",
        )
    )

    coverage_end = parse_reference_date(
        member.get(
            "coverage_end",
            "",
        )
    )

    if coverage_start is None or coverage_end is None:
        return EligibilityDecision(
            is_eligible=False,
            reason=(
                f"Member '{member_id}' has missing or invalid "
                "coverage dates."
            ),
        )

    if coverage_start > coverage_end:
        return EligibilityDecision(
            is_eligible=False,
            reason=(
                f"Member '{member_id}' has an invalid coverage "
                "period because coverage_start occurs after "
                "coverage_end."
            ),
        )

    if service_date < coverage_start:
        return EligibilityDecision(
            is_eligible=False,
            reason=(
                f"Member '{member_id}' coverage had not started "
                f"on service date {service_date.isoformat()}. "
                f"Coverage begins "
                f"{coverage_start.isoformat()}."
            ),
        )

    if service_date > coverage_end:
        return EligibilityDecision(
            is_eligible=False,
            reason=(
                f"Member '{member_id}' coverage was not active "
                f"on service date {service_date.isoformat()}. "
                f"Coverage ended "
                f"{coverage_end.isoformat()}."
            ),
        )

    return EligibilityDecision(
        is_eligible=True,
        reason=(
            f"Member '{member_id}' exists, is active, and had "
            f"coverage on service date "
            f"{service_date.isoformat()}."
        ),
    )