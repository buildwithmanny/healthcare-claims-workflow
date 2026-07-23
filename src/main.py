from collections import Counter

from src.claim_loader import (
    load_project_data,
    print_source_summary,
)
from src.database import (
    fetch_claim_status_summary,
    fetch_validation_failures,
    reset_workflow_data,
    test_connection,
)
from src.validator import (
    build_active_diagnosis_codes,
)
from src.workflow_engine import (
    ClaimIntakeResult,
    process_claim_batch,
)


def print_claim_results(
    results: list[ClaimIntakeResult],
) -> None:
    """
    Print the final Day 3 result for each claim.
    """
    print("\nClaim Intake Results")
    print("--------------------")

    for result in results:
        print(
            f"{result.claim_id}: "
            f"{result.final_status.value}"
        )

        for error in result.validation_errors:
            print(f"  - {error}")


def print_result_totals(
    results: list[ClaimIntakeResult],
) -> None:
    """
    Print totals grouped by final workflow status.
    """
    totals = Counter(
        result.final_status.value
        for result in results
    )

    print("\nProcessing Totals")
    print("-----------------")

    for status, count in sorted(
        totals.items()
    ):
        print(f"{status}: {count}")


def print_database_summary() -> None:
    """
    Print claim totals stored in PostgreSQL.
    """
    summary = fetch_claim_status_summary()

    print("\nPostgreSQL Status Summary")
    print("-------------------------")

    for row in summary:
        print(
            f"{row['current_status']}: "
            f"{row['claim_count']}"
        )


def print_audit_failures() -> None:
    """
    Print validation failures retrieved from audit history.
    """
    failures = fetch_validation_failures()

    print("\nValidation Failure Audit History")
    print("--------------------------------")

    if not failures:
        print("No validation failures were recorded.")
        return

    for failure in failures:
        print(
            f"{failure['claim_id']}: "
            f"{failure['previous_status']} -> "
            f"{failure['new_status']}"
        )

        print(
            f"  Reason: {failure['event_reason']}"
        )


def main() -> None:
    """
    Run the Day 3 claim-intake and validation workflow.
    """
    print("Healthcare Claims Workflow")
    print("==========================")

    print("\nLoading synthetic project data...")

    project_data = load_project_data()

    print_source_summary(
        project_data
    )

    print("\nTesting PostgreSQL connection...")

    database_name = test_connection()

    print(
        "Connected successfully to PostgreSQL "
        f"database: {database_name}"
    )

    print("\nResetting local workflow demo data...")

    reset_workflow_data()

    print("Workflow tables reset successfully.")

    active_diagnosis_codes = (
        build_active_diagnosis_codes(
            project_data["diagnosis_codes"]
        )
    )

    print(
        "\nProcessing claims through intake "
        "and validation..."
    )

    results = process_claim_batch(
        claims=project_data["claims"],
        active_diagnosis_codes=(
            active_diagnosis_codes
        ),
    )

    print_claim_results(
        results
    )

    print_result_totals(
        results
    )

    print_database_summary()

    print_audit_failures()

    print("\nDay 3 workflow completed successfully.")


if __name__ == "__main__":
    main()