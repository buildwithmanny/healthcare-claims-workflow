import csv
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.database import (
    fetch_claim_report_rows,
    fetch_claim_status_summary,
    fetch_exception_report_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIRECTORY = PROJECT_ROOT / "reports"


def serialize_value(
    value: Any,
) -> Any:
    """
    Convert PostgreSQL values into JSON- and CSV-safe values.
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


def write_claim_summary(
    rows: list[dict[str, Any]],
) -> Path:
    """
    Write the complete claim-status report as CSV.
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


def write_exception_report(
    rows: list[dict[str, Any]],
) -> Path:
    """
    Write all non-approved workflow outcomes as JSON.
    """
    output_path = (
        REPORTS_DIRECTORY
        / "exception_report.json"
    )

    report = {
        "version": "1.0",
        "exception_count": len(
            rows
        ),
        "claims": [
            serialize_row(
                row
            )
            for row in rows
        ],
    }

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


def write_workflow_summary(
    status_rows: list[dict[str, Any]],
) -> Path:
    """
    Write aggregate workflow results as JSON.
    """
    output_path = (
        REPORTS_DIRECTORY
        / "workflow_summary.json"
    )

    status_counts = {
        row["current_status"]: int(
            row["claim_count"]
        )
        for row in status_rows
    }

    total_claims = sum(
        status_counts.values()
    )

    approved_claims = status_counts.get(
        "APPROVED",
        0,
    )

    approval_rate = (
        round(
            (
                approved_claims
                / total_claims
            )
            * 100,
            2,
        )
        if total_claims
        else 0.0
    )

    report = {
        "version": "1.0",
        "total_claims": total_claims,
        "approved_claims": approved_claims,
        "approval_rate_percent": (
            approval_rate
        ),
        "status_counts": status_counts,
    }

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


def generate_reports() -> dict[str, Path]:
    """
    Generate all Version 1 operational reports.

    Returns:
        A mapping of report names to generated file paths.
    """
    REPORTS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    claim_rows = fetch_claim_report_rows()
    exception_rows = (
        fetch_exception_report_rows()
    )
    status_rows = (
        fetch_claim_status_summary()
    )

    return {
        "claim_summary": write_claim_summary(
            claim_rows
        ),
        "exception_report": (
            write_exception_report(
                exception_rows
            )
        ),
        "workflow_summary": (
            write_workflow_summary(
                status_rows
            )
        ),
    }