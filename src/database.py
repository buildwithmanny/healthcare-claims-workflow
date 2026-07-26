from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.config import DB_CONFIG


def get_connection():
    """
    Create and return a PostgreSQL database connection.
    """
    return psycopg.connect(
        **DB_CONFIG
    )


def test_connection() -> str:
    """
    Test the PostgreSQL connection.

    Returns:
        The connected PostgreSQL database name.
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database();"
            )

            result = cursor.fetchone()

    if result is None:
        raise RuntimeError(
            "PostgreSQL did not return a database name."
        )

    return result[0]


def blank_to_none(
    value: object,
) -> object | None:
    """
    Convert blank strings to None for PostgreSQL NULL values.
    """
    if value is None:
        return None

    if isinstance(
        value,
        str,
    ):
        stripped_value = value.strip()

        if stripped_value == "":
            return None

        return stripped_value

    return value


def parse_date_or_none(
    value: object,
) -> date | None:
    """
    Parse an ISO date.

    Invalid or blank values become None so invalid claims can still be
    persisted and their validation failures can be audited.
    """
    cleaned_value = blank_to_none(
        value
    )

    if cleaned_value is None:
        return None

    try:
        return date.fromisoformat(
            str(cleaned_value)
        )

    except ValueError:
        return None


def parse_decimal_or_none(
    value: object,
) -> Decimal | None:
    """
    Parse a decimal value.

    Invalid or blank values become None so invalid claims can still be
    persisted and their validation failures can be audited.
    """
    cleaned_value = blank_to_none(
        value
    )

    if cleaned_value is None:
        return None

    try:
        return Decimal(
            str(cleaned_value)
        )

    except InvalidOperation:
        return None


def upsert_claim_record(
    cursor: Any,
    claim: dict[str, str],
    current_status: str,
) -> None:
    """
    Insert a claim or reset its local demonstration record.

    The application resets local workflow data before each demonstration
    run, so this upsert is used only for repeatable development runs.
    """
    cursor.execute(
        """
        INSERT INTO claims (
            claim_id,
            member_id,
            provider_id,
            diagnosis_code,
            procedure_code,
            service_date,
            billed_amount,
            allowed_amount,
            submitted_date,
            current_status
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            NULL,
            %s,
            %s
        )
        ON CONFLICT (claim_id)
        DO UPDATE SET
            member_id = EXCLUDED.member_id,
            provider_id = EXCLUDED.provider_id,
            diagnosis_code = EXCLUDED.diagnosis_code,
            procedure_code = EXCLUDED.procedure_code,
            service_date = EXCLUDED.service_date,
            billed_amount = EXCLUDED.billed_amount,
            allowed_amount = NULL,
            submitted_date = EXCLUDED.submitted_date,
            current_status = EXCLUDED.current_status,
            updated_at = CURRENT_TIMESTAMP;
        """,
        (
            claim["claim_id"].strip(),
            blank_to_none(
                claim.get("member_id")
            ),
            blank_to_none(
                claim.get("provider_id")
            ),
            blank_to_none(
                claim.get("diagnosis_code")
            ),
            blank_to_none(
                claim.get("procedure_code")
            ),
            parse_date_or_none(
                claim.get("service_date")
            ),
            parse_decimal_or_none(
                claim.get("billed_amount")
            ),
            parse_date_or_none(
                claim.get("submitted_date")
            ),
            current_status,
        ),
    )


def update_claim_status(
    cursor: Any,
    claim_id: str,
    expected_current_status: str,
    new_status: str,
) -> None:
    """
    Update a claim only when its persisted state matches expectations.

    This prevents an outdated or incorrectly ordered workflow process
    from overwriting a claim that has already moved to another state.

    Args:
        cursor: Active PostgreSQL cursor.
        claim_id: Claim being transitioned.
        expected_current_status: State the workflow believes the claim
        currently occupies.
        new_status: Requested next state.

    Raises:
        RuntimeError:
            If the claim does not exist or its actual state differs
            from expected_current_status.
    """
    cursor.execute(
        """
        UPDATE claims
        SET
            current_status = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE claim_id = %s
          AND current_status = %s
        RETURNING current_status;
        """,
        (
            new_status,
            claim_id,
            expected_current_status,
        ),
    )

    result = cursor.fetchone()

    if result is not None:
        return

    cursor.execute(
        """
        SELECT
            current_status
        FROM claims
        WHERE claim_id = %s;
        """,
        (
            claim_id,
        ),
    )

    existing_claim = cursor.fetchone()

    if existing_claim is None:
        raise RuntimeError(
            f"Claim '{claim_id}' does not exist."
        )

    actual_status = existing_claim[0]

    raise RuntimeError(
        f"Claim '{claim_id}' state conflict. "
        f"Expected current state "
        f"'{expected_current_status}', "
        f"but PostgreSQL contains "
        f"'{actual_status}'."
    )


def update_claim_allowed_amount(
    cursor: Any,
    claim_id: str,
    allowed_amount: Decimal,
) -> None:
    """
    Store the successful pricing result for one claim.
    """
    cursor.execute(
        """
        UPDATE claims
        SET
            allowed_amount = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE claim_id = %s;
        """,
        (
            allowed_amount,
            claim_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Allowed amount could not be stored for "
            f"claim '{claim_id}'."
        )


def find_prior_duplicate_claim_id(
    cursor: Any,
    claim: dict[str, str],
) -> str | None:
    """
    Find a previously processed claim matching the duplicate key.

    The duplicate rule compares:

    - member_id
    - provider_id
    - procedure_code
    - service_date
    """
    claim_id = claim.get(
        "claim_id",
        "",
    ).strip()

    member_id = claim.get(
        "member_id",
        "",
    ).strip()

    provider_id = claim.get(
        "provider_id",
        "",
    ).strip()

    procedure_code = claim.get(
        "procedure_code",
        "",
    ).strip()

    service_date = parse_date_or_none(
        claim.get(
            "service_date"
        )
    )

    cursor.execute(
        """
        SELECT
            claim_id
        FROM claims
        WHERE claim_id <> %s
          AND member_id = %s
          AND provider_id = %s
          AND procedure_code = %s
          AND service_date = %s
          AND current_status IN (
              'DUPLICATE_CHECK',
              'PRICING',
              'PRICING_RETRY',
              'FRAUD_REVIEW',
              'MANUAL_REVIEW',
              'APPROVED'
          )
        ORDER BY
            created_at,
            claim_id
        LIMIT 1;
        """,
        (
            claim_id,
            member_id,
            provider_id,
            procedure_code,
            service_date,
        ),
    )

    result = cursor.fetchone()

    if result is None:
        return None

    return result[0]


def count_prior_member_claims(
    cursor: Any,
    claim: dict[str, str],
    period_days: int,
) -> int:
    """
    Count qualifying prior claims for the same member.

    The current claim is excluded.
    """
    claim_id = claim.get(
        "claim_id",
        "",
    ).strip()

    member_id = claim.get(
        "member_id",
        "",
    ).strip()

    service_date = parse_date_or_none(
        claim.get(
            "service_date"
        )
    )

    if service_date is None:
        return 0

    period_start = (
        service_date
        - timedelta(
            days=period_days
        )
    )

    cursor.execute(
        """
        SELECT
            COUNT(*)
        FROM claims
        WHERE claim_id <> %s
          AND member_id = %s
          AND service_date BETWEEN %s AND %s
          AND current_status IN (
              'PRICING',
              'PRICING_RETRY',
              'FRAUD_REVIEW',
              'MANUAL_REVIEW',
              'APPROVED'
          );
        """,
        (
            claim_id,
            member_id,
            period_start,
            service_date,
        ),
    )

    result = cursor.fetchone()

    if result is None:
        return 0

    return int(
        result[0]
    )


def reset_workflow_data() -> None:
    """
    Clear workflow records for repeatable local development runs.

    This is a development helper, not a production data pattern.
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE TABLE
                    manual_review_queue,
                    retry_queue,
                    claim_events,
                    claims
                RESTART IDENTITY;
                """
            )


def fetch_claim_status_summary() -> list[dict[str, Any]]:
    """
    Return claim totals grouped by current workflow status.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    current_status,
                    COUNT(*) AS claim_count
                FROM claims
                GROUP BY current_status
                ORDER BY current_status;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_validation_failures() -> list[dict[str, Any]]:
    """
    Return validation-failure audit events.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    previous_status,
                    new_status,
                    processing_step,
                    event_reason,
                    created_at
                FROM claim_events
                WHERE new_status = 'VALIDATION_FAILED'
                ORDER BY claim_id, event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_eligibility_decisions() -> list[dict[str, Any]]:
    """
    Return all audit events created by eligibility processing.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    previous_status,
                    new_status,
                    processing_step,
                    event_reason,
                    created_at
                FROM claim_events
                WHERE processing_step = 'ELIGIBILITY'
                ORDER BY claim_id, event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_duplicate_decisions() -> list[dict[str, Any]]:
    """
    Return all audit events created by duplicate processing.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    previous_status,
                    new_status,
                    processing_step,
                    event_reason,
                    created_at
                FROM claim_events
                WHERE processing_step = 'DUPLICATE_CHECK'
                ORDER BY claim_id, event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_pricing_decisions() -> list[dict[str, Any]]:
    """
    Return all audit events created by pricing processing.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    previous_status,
                    new_status,
                    processing_step,
                    event_reason,
                    created_at
                FROM claim_events
                WHERE processing_step = 'PRICING'
                ORDER BY claim_id, event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_fraud_review_decisions() -> list[dict[str, Any]]:
    """
    Return all audit events created by fraud-review processing.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    previous_status,
                    new_status,
                    processing_step,
                    event_reason,
                    created_at
                FROM claim_events
                WHERE processing_step = 'FRAUD_REVIEW'
                ORDER BY claim_id, event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_priced_claims() -> list[dict[str, Any]]:
    """
    Return claims that received a successful allowed amount.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    procedure_code,
                    billed_amount,
                    allowed_amount,
                    current_status
                FROM claims
                WHERE allowed_amount IS NOT NULL
                ORDER BY claim_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_claim_report_rows() -> list[dict[str, Any]]:
    """
    Return all claims for the claim-summary report.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    member_id,
                    provider_id,
                    diagnosis_code,
                    procedure_code,
                    service_date,
                    billed_amount,
                    allowed_amount,
                    submitted_date,
                    current_status
                FROM claims
                ORDER BY claim_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_exception_report_rows() -> list[dict[str, Any]]:
    """
    Return claims that did not reach automatic approval.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    member_id,
                    provider_id,
                    procedure_code,
                    service_date,
                    billed_amount,
                    allowed_amount,
                    current_status
                FROM claims
                WHERE current_status IN (
                    'VALIDATION_FAILED',
                    'DENIED',
                    'DUPLICATE',
                    'PRICING_RETRY',
                    'MANUAL_REVIEW',
                    'FAILED'
                )
                ORDER BY claim_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_claim_current_state(
    claim_id: str,
) -> dict[str, Any] | None:
    """
    Answer: Where is this claim now?

    Returns the current persisted state and the time the claim record
    was most recently updated.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    current_status,
                    created_at,
                    updated_at
                FROM claims
                WHERE claim_id = %s;
                """,
                (
                    claim_id,
                ),
            )

            result = cursor.fetchone()

    if result is None:
        return None

    return dict(
        result
    )


def fetch_claim_history(
    claim_id: str,
) -> list[dict[str, Any]]:
    """
    Answer:

    - Where has this claim been?
    - Why did each status change?
    - When did each change occur?
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    event_id,
                    claim_id,
                    previous_status,
                    new_status,
                    processing_step,
                    event_reason,
                    retry_attempt,
                    created_at
                FROM claim_events
                WHERE claim_id = %s
                ORDER BY
                    created_at,
                    event_id;
                """,
                (
                    claim_id,
                ),
            )

            return list(
                cursor.fetchall()
            )


def fetch_claim_journey(
    claim_id: str,
) -> list[dict[str, Any]]:
    """
    Return the combined current-state and history view for one claim.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    current_status,
                    claim_updated_at,
                    event_id,
                    previous_status,
                    new_status,
                    processing_step,
                    event_reason,
                    retry_attempt,
                    event_created_at
                FROM claim_journey
                WHERE claim_id = %s
                ORDER BY
                    event_created_at,
                    event_id;
                """,
                (
                    claim_id,
                ),
            )

            return list(
                cursor.fetchall()
            )