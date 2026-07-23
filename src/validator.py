from datetime import date
from decimal import Decimal, InvalidOperation


REQUIRED_FIELDS = (
    "claim_id",
    "member_id",
    "provider_id",
    "diagnosis_code",
    "procedure_code",
    "service_date",
    "billed_amount",
    "submitted_date",
)


def is_blank(value: object) -> bool:
    """
    Return True when a value is missing or contains only whitespace.
    """
    return value is None or str(value).strip() == ""


def build_active_diagnosis_codes(
    diagnosis_records: list[dict[str, str]],
) -> set[str]:
    """
    Build a set of active diagnosis codes from reference data.

    Only records with active=TRUE are considered valid.
    """
    active_codes: set[str] = set()

    for record in diagnosis_records:
        code = record.get(
            "diagnosis_code",
            "",
        ).strip()

        active_flag = record.get(
            "active",
            "",
        ).strip().upper()

        if code and active_flag == "TRUE":
            active_codes.add(code)

    return active_codes


def validate_iso_date(
    value: str,
    field_name: str,
    errors: list[str],
) -> None:
    """
    Validate that a value is an ISO-formatted date.

    Expected format:
        YYYY-MM-DD
    """
    try:
        date.fromisoformat(value)

    except ValueError:
        errors.append(
            f"{field_name} must use YYYY-MM-DD format."
        )


def validate_billed_amount(
    value: str,
    errors: list[str],
) -> None:
    """
    Validate that billed amount is numeric and greater than zero.
    """
    try:
        amount = Decimal(value)

    except InvalidOperation:
        errors.append(
            "billed_amount must be a valid number."
        )
        return

    if amount <= 0:
        errors.append(
            "billed_amount must be greater than zero."
        )


def validate_claim(
    claim: dict[str, str],
    active_diagnosis_codes: set[str],
) -> list[str]:
    """
    Validate a single incoming claim.

    Validation includes:
    - Required fields
    - Member ID presence
    - Diagnosis code validity
    - Procedure code presence
    - Service-date format
    - Submitted-date format
    - Billed amount validity

    Args:
        claim: Raw claim record loaded from claims.csv.
        active_diagnosis_codes: Valid active diagnosis codes.

    Returns:
        A list of validation errors.

        An empty list means the claim passed validation.
    """
    errors: list[str] = []

    for field_name in REQUIRED_FIELDS:
        if is_blank(claim.get(field_name)):
            errors.append(
                f"{field_name} is required."
            )

    diagnosis_code = claim.get(
        "diagnosis_code",
        "",
    ).strip()

    if (
        diagnosis_code
        and diagnosis_code not in active_diagnosis_codes
    ):
        errors.append(
            f"diagnosis_code '{diagnosis_code}' is invalid or inactive."
        )

    service_date = claim.get(
        "service_date",
        "",
    ).strip()

    if service_date:
        validate_iso_date(
            service_date,
            "service_date",
            errors,
        )

    submitted_date = claim.get(
        "submitted_date",
        "",
    ).strip()

    if submitted_date:
        validate_iso_date(
            submitted_date,
            "submitted_date",
            errors,
        )

    billed_amount = claim.get(
        "billed_amount",
        "",
    ).strip()

    if billed_amount:
        validate_billed_amount(
            billed_amount,
            errors,
        )

    return errors