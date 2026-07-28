import csv
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row

from src.database import (
    fetch_claim_report_rows,
    get_connection,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIRECTORY = PROJECT_ROOT / "reports"


def serialize_value(
    value: Any,
) -> Any:
    """
    Convert PostgreSQL and Python values into report-safe values.

    Decimal values are formatted with two decimal places.
    Date and timestamp values use ISO 8601 format.
    """
    if isinstance(
        value,
        Decimal,
    ):
        return f"{value:.2f}"

    if isinstance(
        value,
        (date, datetime),
    ):
        return value.isoformat()

    return value


def serialize_row(
    row: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert every value in a database row into a report-safe value.
    """
    return {
        key: serialize_value(
            value
        )
        for key, value in row.items()
    }


def serialize_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Convert a collection of database rows into report-safe rows.
    """
    return [
        serialize_row(
            row
        )
        for row in rows
    ]


def calculate_percentage(
    numerator: int,
    denominator: int,
) -> float:
    """
    Calculate a percentage rounded to two decimal places.

    A zero denominator returns 0.0.
    """
    if denominator == 0:
        return 0.0

    return round(
        (
            numerator
            / denominator
        )
        * 100,
        2,
    )


def fetch_status_counts() -> dict[str, int]:
    """
    Return claim counts grouped by current status.
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

            rows = list(
                cursor.fetchall()
            )

    return {
        str(
            row["current_status"]
        ): int(
            row["claim_count"]
        )
        for row in rows
    }


def fetch_claim_count_metrics() -> dict[str, int]:
    """
    Return aggregate claim counts.

    Rejected claims are defined as claims that ended in either:

    - VALIDATION_FAILED
    - DUPLICATE

    DENIED remains separate because it represents an eligibility or
    reviewer decision rather than an intake rejection.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS claims_received,

                    COUNT(*) FILTER (
                        WHERE current_status = 'APPROVED'
                    ) AS claims_approved,

                    COUNT(*) FILTER (
                        WHERE current_status = 'DENIED'
                    ) AS claims_denied,

                    COUNT(*) FILTER (
                        WHERE current_status IN (
                            'VALIDATION_FAILED',
                            'DUPLICATE'
                        )
                    ) AS claims_rejected,

                    COUNT(*) FILTER (
                        WHERE current_status = 'MANUAL_REVIEW'
                    ) AS claims_in_manual_review,

                    COUNT(*) FILTER (
                        WHERE current_status = 'FAILED'
                    ) AS claims_failed

                FROM claims;
                """
            )

            row = cursor.fetchone()

    if row is None:
        return {
            "claims_received": 0,
            "claims_approved": 0,
            "claims_denied": 0,
            "claims_rejected": 0,
            "claims_in_manual_review": 0,
            "claims_failed": 0,
        }

    return {
        "claims_received": int(
            row["claims_received"]
        ),
        "claims_approved": int(
            row["claims_approved"]
        ),
        "claims_denied": int(
            row["claims_denied"]
        ),
        "claims_rejected": int(
            row["claims_rejected"]
        ),
        "claims_in_manual_review": int(
            row["claims_in_manual_review"]
        ),
        "claims_failed": int(
            row["claims_failed"]
        ),
    }


def fetch_retry_metrics() -> dict[str, Any]:
    """
    Return aggregate retry-queue metrics.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS retry_queue_records,

                    COUNT(
                        DISTINCT claim_id
                    ) AS claims_requiring_retries,

                    COALESCE(
                        AVG(retry_count),
                        0
                    ) AS average_retry_count,

                    COUNT(*) FILTER (
                        WHERE retry_status = 'SUCCEEDED'
                    ) AS successful_retries,

                    COUNT(*) FILTER (
                        WHERE retry_status = 'EXHAUSTED'
                    ) AS exhausted_retries,

                    COUNT(*) FILTER (
                        WHERE retry_status = 'CANCELLED'
                    ) AS cancelled_retries,

                    COUNT(*) FILTER (
                        WHERE retry_status IN (
                            'PENDING',
                            'PROCESSING'
                        )
                    ) AS open_retries

                FROM retry_queue;
                """
            )

            row = cursor.fetchone()

    if row is None:
        return {
            "retry_queue_records": 0,
            "claims_requiring_retries": 0,
            "average_retry_count": 0.0,
            "successful_retries": 0,
            "exhausted_retries": 0,
            "cancelled_retries": 0,
            "open_retries": 0,
            "retry_success_percentage": 0.0,
        }

    retry_queue_records = int(
        row["retry_queue_records"]
    )

    successful_retries = int(
        row["successful_retries"]
    )

    return {
        "retry_queue_records": (
            retry_queue_records
        ),
        "claims_requiring_retries": int(
            row["claims_requiring_retries"]
        ),
        "average_retry_count": round(
            float(
                row["average_retry_count"]
            ),
            2,
        ),
        "successful_retries": (
            successful_retries
        ),
        "exhausted_retries": int(
            row["exhausted_retries"]
        ),
        "cancelled_retries": int(
            row["cancelled_retries"]
        ),
        "open_retries": int(
            row["open_retries"]
        ),
        "retry_success_percentage": (
            calculate_percentage(
                successful_retries,
                retry_queue_records,
            )
        ),
    }


def fetch_manual_review_metrics() -> dict[str, int]:
    """
    Return aggregate manual-review queue metrics.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS manual_review_volume,

                    COUNT(*) FILTER (
                        WHERE review_status = 'APPROVED'
                    ) AS reviewer_approvals,

                    COUNT(*) FILTER (
                        WHERE review_status = 'DENIED'
                    ) AS reviewer_denials,

                    COUNT(*) FILTER (
                        WHERE review_status IN (
                            'PENDING',
                            'IN_REVIEW'
                        )
                    ) AS open_manual_reviews,

                    COUNT(*) FILTER (
                        WHERE resolved_at IS NOT NULL
                    ) AS resolved_manual_reviews

                FROM manual_review_queue;
                """
            )

            row = cursor.fetchone()

    if row is None:
        return {
            "manual_review_volume": 0,
            "reviewer_approvals": 0,
            "reviewer_denials": 0,
            "open_manual_reviews": 0,
            "resolved_manual_reviews": 0,
        }

    return {
        "manual_review_volume": int(
            row["manual_review_volume"]
        ),
        "reviewer_approvals": int(
            row["reviewer_approvals"]
        ),
        "reviewer_denials": int(
            row["reviewer_denials"]
        ),
        "open_manual_reviews": int(
            row["open_manual_reviews"]
        ),
        "resolved_manual_reviews": int(
            row["resolved_manual_reviews"]
        ),
    }


def fetch_operational_metrics() -> dict[str, Any]:
    """
    Build the complete operational workflow metrics report.
    """
    generated_at = datetime.now(
        timezone.utc
    ).isoformat()

    claim_counts = fetch_claim_count_metrics()
    status_counts = fetch_status_counts()
    retry_metrics = fetch_retry_metrics()
    manual_review_metrics = (
        fetch_manual_review_metrics()
    )

    claims_received = claim_counts[
        "claims_received"
    ]

    claims_approved = claim_counts[
        "claims_approved"
    ]

    claims_denied = claim_counts[
        "claims_denied"
    ]

    claims_rejected = claim_counts[
        "claims_rejected"
    ]

    reviewer_approvals = manual_review_metrics[
        "reviewer_approvals"
    ]

    automatic_approvals = max(
        claims_approved
        - reviewer_approvals,
        0,
    )

    return {
        "generated_at_utc": generated_at,
        "report_version": "1.0",
        "claim_summary": {
            **claim_counts,
            "automatic_approvals": (
                automatic_approvals
            ),
            "reviewer_approvals": (
                reviewer_approvals
            ),
        },
        "workflow_metrics": {
            "claims_by_status": status_counts,
            "approval_percentage": (
                calculate_percentage(
                    claims_approved,
                    claims_received,
                )
            ),
            "denial_percentage": (
                calculate_percentage(
                    claims_denied,
                    claims_received,
                )
            ),
            "rejection_percentage": (
                calculate_percentage(
                    claims_rejected,
                    claims_received,
                )
            ),
            **retry_metrics,
            **manual_review_metrics,
        },
        "metric_definitions": {
            "claims_received": (
                "All claim records stored in the claims table."
            ),
            "claims_rejected": (
                "Claims ending in VALIDATION_FAILED or "
                "DUPLICATE."
            ),
            "claims_in_manual_review": (
                "Claims whose current status remains "
                "MANUAL_REVIEW."
            ),
            "claims_requiring_retries": (
                "Distinct claims represented in retry_queue."
            ),
            "average_retry_count": (
                "Average retry_count across retry_queue "
                "records."
            ),
            "manual_review_volume": (
                "Total records created in "
                "manual_review_queue."
            ),
            "approval_percentage": (
                "Approved claims divided by claims received."
            ),
        },
    }


def fetch_validation_failure_rows() -> list[dict[str, Any]]:
    """
    Return validation failure events.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    e.claim_id,
                    c.member_id,
                    c.provider_id,
                    c.diagnosis_code,
                    c.procedure_code,
                    c.service_date,
                    c.current_status,
                    e.event_reason,
                    e.created_at

                FROM claim_events AS e

                INNER JOIN claims AS c
                    ON c.claim_id = e.claim_id

                WHERE e.new_status = 'VALIDATION_FAILED'

                ORDER BY
                    e.claim_id,
                    e.event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_eligibility_failure_rows() -> list[dict[str, Any]]:
    """
    Return claims that failed eligibility processing.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    e.claim_id,
                    c.member_id,
                    c.service_date,
                    c.current_status,
                    e.event_reason,
                    e.created_at

                FROM claim_events AS e

                INNER JOIN claims AS c
                    ON c.claim_id = e.claim_id

                WHERE e.new_status = 'INELIGIBLE'

                ORDER BY
                    e.claim_id,
                    e.event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_duplicate_rows() -> list[dict[str, Any]]:
    """
    Return claims identified as duplicates.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    e.claim_id,
                    c.member_id,
                    c.provider_id,
                    c.procedure_code,
                    c.service_date,
                    c.current_status,
                    e.event_reason,
                    e.created_at

                FROM claim_events AS e

                INNER JOIN claims AS c
                    ON c.claim_id = e.claim_id

                WHERE e.new_status = 'DUPLICATE'

                ORDER BY
                    e.claim_id,
                    e.event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_pricing_failure_rows() -> list[dict[str, Any]]:
    """
    Return pricing and retry failure events.

    A single claim may have multiple pricing failure events because
    each retry attempt is audited separately.
    """
    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    e.claim_id,
                    c.procedure_code,
                    c.billed_amount,
                    c.allowed_amount,
                    c.current_status,
                    e.previous_status,
                    e.new_status,
                    e.retry_attempt,
                    e.event_reason,
                    e.created_at

                FROM claim_events AS e

                INNER JOIN claims AS c
                    ON c.claim_id = e.claim_id

                WHERE e.processing_step IN (
                    'PRICING',
                    'PRICING_RETRY'
                )
                  AND e.new_status IN (
                      'PRICING_RETRY',
                      'MANUAL_REVIEW',
                      'FAILED'
                  )

                ORDER BY
                    e.claim_id,
                    e.event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_exhausted_retry_rows() -> list[dict[str, Any]]:
    """
    Return retry records that exhausted all automated attempts.
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
                    last_error,
                    created_at,
                    updated_at

                FROM retry_queue

                WHERE retry_status = 'EXHAUSTED'

                ORDER BY retry_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def fetch_manual_review_rows() -> list[dict[str, Any]]:
    """
    Return all manual-review queue activity.
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


def fetch_system_error_rows() -> list[dict[str, Any]]:
    """
    Return unexpected technical failures recorded by the workflow.
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

                WHERE processing_step = 'SYSTEM_ERROR'

                ORDER BY
                    claim_id,
                    event_id;
                """
            )

            return list(
                cursor.fetchall()
            )


def build_exception_category(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Build one exception-report category.

    The report distinguishes event count from unique affected claims.
    """
    claim_ids = {
        str(
            row["claim_id"]
        )
        for row in rows
    }

    return {
        "event_count": len(
            rows
        ),
        "affected_claim_count": len(
            claim_ids
        ),
        "affected_claim_ids": sorted(
            claim_ids
        ),
        "details": serialize_rows(
            rows
        ),
    }


def fetch_exception_report() -> dict[str, Any]:
    """
    Build the complete exception report.
    """
    validation_failures = (
        fetch_validation_failure_rows()
    )

    eligibility_failures = (
        fetch_eligibility_failure_rows()
    )

    duplicates = fetch_duplicate_rows()

    pricing_failures = (
        fetch_pricing_failure_rows()
    )

    exhausted_retries = (
        fetch_exhausted_retry_rows()
    )

    manual_reviews = (
        fetch_manual_review_rows()
    )

    system_errors = fetch_system_error_rows()

    return {
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "report_version": "1.0",
        "categories": {
            "validation_failures": (
                build_exception_category(
                    validation_failures
                )
            ),
            "eligibility_failures": (
                build_exception_category(
                    eligibility_failures
                )
            ),
            "duplicates": (
                build_exception_category(
                    duplicates
                )
            ),
            "pricing_failures": (
                build_exception_category(
                    pricing_failures
                )
            ),
            "exhausted_retries": (
                build_exception_category(
                    exhausted_retries
                )
            ),
            "manual_reviews": (
                build_exception_category(
                    manual_reviews
                )
            ),
            "system_errors": (
                build_exception_category(
                    system_errors
                )
            ),
        },
    }


def write_json_report(
    filename: str,
    report: dict[str, Any],
) -> Path:
    """
    Write a dictionary as an indented JSON report.
    """
    output_path = (
        REPORTS_DIRECTORY
        / filename
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            report,
            file,
            indent=4,
        )

        file.write(
            "\n"
        )

    return output_path


def write_claim_summary_csv(
    rows: list[dict[str, Any]],
) -> Path:
    """
    Write one detailed row for every claim.
    """
    output_path = (
        REPORTS_DIRECTORY
        / "claim_summary.csv"
    )

    fieldnames = [
        "claim_id",
        "member_id",
        "provider_id",
        "diagnosis_code",
        "procedure_code",
        "service_date",
        "billed_amount",
        "allowed_amount",
        "submitted_date",
        "current_status",
    ]

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(
                serialize_row(
                    row
                )
            )

    return output_path


def write_claim_summary_json(
    operational_metrics: dict[str, Any],
) -> Path:
    """
    Write aggregate claim-summary counts.
    """
    report = {
        "generated_at_utc": (
            operational_metrics[
                "generated_at_utc"
            ]
        ),
        "report_version": (
            operational_metrics[
                "report_version"
            ]
        ),
        "claim_summary": (
            operational_metrics[
                "claim_summary"
            ]
        ),
        "definitions": {
            "claims_rejected": (
                "VALIDATION_FAILED plus DUPLICATE claims."
            ),
            "claims_denied": (
                "Claims denied by eligibility processing "
                "or manual review."
            ),
            "claims_in_manual_review": (
                "Claims that currently remain in "
                "MANUAL_REVIEW."
            ),
        },
    }

    return write_json_report(
        "claim_summary.json",
        report,
    )


def write_exception_report(
    exception_report: dict[str, Any],
) -> Path:
    """
    Write categorized workflow exceptions.
    """
    return write_json_report(
        "exception_report.json",
        exception_report,
    )


def write_workflow_metrics(
    operational_metrics: dict[str, Any],
) -> Path:
    """
    Write the full operational metrics report.
    """
    return write_json_report(
        "workflow_metrics.json",
        operational_metrics,
    )


def write_legacy_workflow_summary(
    operational_metrics: dict[str, Any],
) -> Path:
    """
    Preserve the original concise workflow_summary.json format.

    Existing project documentation and prior project days may still
    reference this file.
    """
    claim_summary = operational_metrics[
        "claim_summary"
    ]

    workflow_metrics = operational_metrics[
        "workflow_metrics"
    ]

    report = {
        "version": "1.0",
        "total_claims": claim_summary[
            "claims_received"
        ],
        "approved_claims": claim_summary[
            "claims_approved"
        ],
        "approval_rate_percent": (
            workflow_metrics[
                "approval_percentage"
            ]
        ),
        "status_counts": (
            workflow_metrics[
                "claims_by_status"
            ]
        ),
    }

    return write_json_report(
        "workflow_summary.json",
        report,
    )


def generate_reports() -> dict[str, Path]:
    """
    Generate all operational reports.

    Returns:
        A mapping of report names to generated file paths.
    """
    REPORTS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    claim_rows = fetch_claim_report_rows()

    operational_metrics = (
        fetch_operational_metrics()
    )

    exception_report = (
        fetch_exception_report()
    )

    return {
        "claim_details": (
            write_claim_summary_csv(
                claim_rows
            )
        ),
        "claim_summary": (
            write_claim_summary_json(
                operational_metrics
            )
        ),
        "exception_report": (
            write_exception_report(
                exception_report
            )
        ),
        "workflow_metrics": (
            write_workflow_metrics(
                operational_metrics
            )
        ),
        "workflow_summary": (
            write_legacy_workflow_summary(
                operational_metrics
            )
        ),
    }