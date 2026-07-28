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
    Convert blank strings to PostgreSQL NULL values.
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


def enqueue_pricing_retry(
    cursor: Any,
    claim_id: str,
    last_error: str,
    max_retries: int,
) -> int:
    """
    Add a temporary pricing failure to the retry queue.
    """
    if max_retries <= 0:
        raise ValueError(
            "max_retries must be greater than zero."
        )

    cursor.execute(
        """
        INSERT INTO retry_queue (
            claim_id,
            failed_step,
            retry_count,
            max_retries,
            next_retry_time,
            retry_status,
            last_error
        )
        VALUES (
            %s,
            'PRICING',
            0,
            %s,
            CURRENT_TIMESTAMP,
            'PENDING',
            %s
        )
        RETURNING retry_id;
        """,
        (
            claim_id,
            max_retries,
            last_error,
        ),
    )

    result = cursor.fetchone()

    if result is None:
        raise RuntimeError(
            "PostgreSQL did not return a retry ID."
        )

    return int(
        result[0]
    )


def start_retry_attempt(
    cursor: Any,
    retry_id: int,
) -> dict[str, Any]:
    """
    Atomically begin one pending retry attempt.
    """
    cursor.execute(
        """
        UPDATE retry_queue
        SET
            retry_count = retry_count + 1,
            retry_status = 'PROCESSING',
            updated_at = CURRENT_TIMESTAMP
        WHERE retry_id = %s
          AND retry_status = 'PENDING'
          AND retry_count < max_retries
        RETURNING
            retry_id,
            claim_id,
            failed_step,
            retry_count,
            max_retries;
        """,
        (
            retry_id,
        ),
    )

    result = cursor.fetchone()

    if result is None:
        raise RuntimeError(
            f"Retry queue item '{retry_id}' could not "
            "start another attempt."
        )

    return {
        "retry_id": int(
            result[0]
        ),
        "claim_id": str(
            result[1]
        ),
        "failed_step": str(
            result[2]
        ),
        "retry_count": int(
            result[3]
        ),
        "max_retries": int(
            result[4]
        ),
    }


def mark_retry_pending(
    cursor: Any,
    retry_id: int,
    last_error: str,
) -> None:
    """
    Return a failed retry attempt to PENDING status.
    """
    cursor.execute(
        """
        UPDATE retry_queue
        SET
            retry_status = 'PENDING',
            next_retry_time = CURRENT_TIMESTAMP,
            last_error = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE retry_id = %s
          AND retry_status = 'PROCESSING';
        """,
        (
            last_error,
            retry_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            f"Retry queue item '{retry_id}' could not "
            "return to PENDING status."
        )


def mark_retry_succeeded(
    cursor: Any,
    retry_id: int,
) -> None:
    """
    Mark a retry queue item as successfully resolved.
    """
    cursor.execute(
        """
        UPDATE retry_queue
        SET
            retry_status = 'SUCCEEDED',
            next_retry_time = NULL,
            last_error = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE retry_id = %s
          AND retry_status = 'PROCESSING';
        """,
        (
            retry_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            f"Retry queue item '{retry_id}' could not "
            "be marked SUCCEEDED."
        )


def mark_retry_exhausted(
    cursor: Any,
    retry_id: int,
    last_error: str,
) -> None:
    """
    Mark a retry queue item as having exhausted all attempts.
    """
    cursor.execute(
        """
        UPDATE retry_queue
        SET
            retry_status = 'EXHAUSTED',
            next_retry_time = NULL,
            last_error = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE retry_id = %s
          AND retry_status = 'PROCESSING';
        """,
        (
            last_error,
            retry_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            f"Retry queue item '{retry_id}' could not "
            "be marked EXHAUSTED."
        )


def mark_retry_cancelled(
    cursor: Any,
    retry_id: int,
    last_error: str,
) -> None:
    """
    Cancel retry processing after a permanent failure is discovered.
    """
    cursor.execute(
        """
        UPDATE retry_queue
        SET
            retry_status = 'CANCELLED',
            next_retry_time = NULL,
            last_error = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE retry_id = %s
          AND retry_status = 'PROCESSING';
        """,
        (
            last_error,
            retry_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            f"Retry queue item '{retry_id}' could not "
            "be marked CANCELLED."
        )


def enqueue_manual_review(
    cursor: Any,
    claim_id: str,
    review_reason: str,
) -> int:
    """
    Add a claim to the manual-review queue.

    If the claim already has an active PENDING or IN_REVIEW queue item,
    the existing review ID is returned.
    """
    cleaned_reason = review_reason.strip()

    if not cleaned_reason:
        raise ValueError(
            "Manual review requires a review_reason."
        )

    cursor.execute(
        """
        SELECT
            review_id
        FROM manual_review_queue
        WHERE claim_id = %s
          AND review_status IN (
              'PENDING',
              'IN_REVIEW'
          )
        ORDER BY review_id
        LIMIT 1;
        """,
        (
            claim_id,
        ),
    )

    existing_review = cursor.fetchone()

    if existing_review is not None:
        return int(
            existing_review[0]
        )

    cursor.execute(
        """
        INSERT INTO manual_review_queue (
            claim_id,
            review_reason,
            review_status,
            reviewer_notes
        )
        VALUES (
            %s,
            %s,
            'PENDING',
            NULL
        )
        RETURNING review_id;
        """,
        (
            claim_id,
            cleaned_reason,
        ),
    )

    result = cursor.fetchone()

    if result is None:
        raise RuntimeError(
            "PostgreSQL did not return a manual-review ID."
        )

    return int(
        result[0]
    )


def mark_manual_review_in_review(
    cursor: Any,
    review_id: int,
) -> None:
    """
    Move one queue item from PENDING to IN_REVIEW.
    """
    cursor.execute(
        """
        UPDATE manual_review_queue
        SET
            review_status = 'IN_REVIEW'
        WHERE review_id = %s
          AND review_status = 'PENDING';
        """,
        (
            review_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            f"Manual-review item '{review_id}' could not "
            "be moved to IN_REVIEW."
        )


def resolve_manual_review(
    cursor: Any,
    review_id: int,
    decision: str,
    reviewer_notes: str,
) -> None:
    """
    Resolve one manual-review queue item.

    The decision must be APPROVED or DENIED.
    """
    normalized_decision = (
        decision.strip().upper()
    )

    if normalized_decision not in {
        "APPROVED",
        "DENIED",
    }:
        raise ValueError(
            "Manual-review decision must be "
            "APPROVED or DENIED."
        )

    cleaned_notes = reviewer_notes.strip()

    if not cleaned_notes:
        raise ValueError(
            "Manual-review resolution requires reviewer_notes."
        )

    cursor.execute(
        """
        UPDATE manual_review_queue
        SET
            review_status = %s,
            reviewer_notes = %s,
            resolved_at = CURRENT_TIMESTAMP
        WHERE review_id = %s
          AND review_status = 'IN_REVIEW';
        """,
        (
            normalized_decision,
            cleaned_notes,
            review_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            f"Manual-review item '{review_id}' could not "
            "be resolved."
        )


def reset_workflow_data() -> None:
    """
    Clear workflow records for repeatable local development runs.
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


def fetch_pending_retry_queue_items() -> list[dict[str, Any]]:
    """
    Return retry queue items waiting for processing.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    retry_id,
                    claim_id,
                    failed_step,
                    retry_count,
                    max_retries,
                    retry_status,
                    last_error
                FROM retry_queue
                WHERE retry_status = 'PENDING'
                ORDER BY retry_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_retry_queue_items() -> list[dict[str, Any]]:
    """
    Return all retry queue records and outcomes.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    retry_id,
                    claim_id,
                    failed_step,
                    retry_count,
                    max_retries,
                    next_retry_time,
                    retry_status,
                    last_error,
                    created_at,
                    updated_at
                FROM retry_queue
                ORDER BY retry_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_pending_manual_review_items() -> list[dict[str, Any]]:
    """
    Return manual-review items waiting for a reviewer.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    review_id,
                    claim_id,
                    review_reason,
                    review_status,
                    reviewer_notes,
                    created_at,
                    resolved_at
                FROM manual_review_queue
                WHERE review_status = 'PENDING'
                ORDER BY review_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_manual_review_queue_items() -> list[dict[str, Any]]:
    """
    Return all manual-review queue records and outcomes.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    review_id,
                    claim_id,
                    review_reason,
                    review_status,
                    reviewer_notes,
                    created_at,
                    resolved_at
                FROM manual_review_queue
                ORDER BY review_id;
                """
            )

            return list(
                cursor.fetchall()
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
                    retry_attempt,
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
    Return eligibility audit events.
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
                    retry_attempt,
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
    Return duplicate-processing audit events.
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
                    retry_attempt,
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
    Return initial pricing and retry pricing audit events.
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
                    retry_attempt,
                    created_at
                FROM claim_events
                WHERE processing_step IN (
                    'PRICING',
                    'PRICING_RETRY'
                )
                ORDER BY claim_id, event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_fraud_review_decisions() -> list[dict[str, Any]]:
    """
    Return fraud-review audit events.
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
                    retry_attempt,
                    created_at
                FROM claim_events
                WHERE processing_step = 'FRAUD_REVIEW'
                ORDER BY claim_id, event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_manual_review_decisions() -> list[dict[str, Any]]:
    """
    Return manual-review decision audit events.
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
                    retry_attempt,
                    created_at
                FROM claim_events
                WHERE processing_step = 'MANUAL_REVIEW'
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
    Return claims that did not reach approval.
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
    Return the current persisted state for one claim.
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
    Return the complete audit history for one claim.
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