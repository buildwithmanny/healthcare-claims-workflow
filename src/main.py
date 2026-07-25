from collections import Counter

from src.claim_loader import (
    load_project_data,
    print_source_summary,
)
from src.database import (
    fetch_claim_status_summary,
    fetch_duplicate_decisions,
    fetch_eligibility_decisions,
    fetch_validation_failures,
    reset_workflow_data,
    test_connection,
)
from src.eligibility import (
    build_member_index,
)
from src.validator import (
    build_active_diagnosis_codes,
)
from src.workflow_engine import (
    ClaimWorkflowResult,
    process_claim_batch,
)


def print_claim_results(
    results: list[ClaimWorkflowResult],
) -> None:
    """
    Print the final Day 5 workflow result for every claim.
    """
    print("\nClaim Workflow Results")
    print("----------------------")

    for result in results:
        print(
            f"{result.claim_id}: "
            f"{result.final_status.value}"
        )

        for error in result.validation_errors:
            print(
                f"  Validation: {error}"
            )

        if result.eligibility_reason is not None:
            print(
                f"  Eligibility: "
                f"{result.eligibility_reason}"
            )

        if result.duplicate_reason is not None:
            print(
                f"  Duplicate check: "
                f"{result.duplicate_reason}"
            )

        if result.duplicate_of_claim_id is not None:
            print(
                f"  Duplicate of: "
                f"{result.duplicate_of_claim_id}"
            )


def print_result_totals(
    results: list[ClaimWorkflowResult],
) -> None:
    """
    Print result totals grouped by final workflow status.
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
        print(
            f"{status}: {count}"
        )


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


def print_validation_audit() -> None:
    """
    Print validation failures from PostgreSQL audit history.
    """
    failures = fetch_validation_failures()

    print("\nValidation Failure Audit History")
    print("--------------------------------")

    if not failures:
        print(
            "No validation failures were recorded."
        )
        return

    for failure in failures:
        print(
            f"{failure['claim_id']}: "
            f"{failure['previous_status']} -> "
            f"{failure['new_status']}"
        )

        print(
            f"  Reason: "
            f"{failure['event_reason']}"
        )


def print_eligibility_audit() -> None:
    """
    Print eligibility decisions from PostgreSQL audit history.
    """
    decisions = fetch_eligibility_decisions()

    print("\nEligibility Audit History")
    print("-------------------------")

    if not decisions:
        print(
            "No eligibility decisions were recorded."
        )
        return

    for decision in decisions:
        print(
            f"{decision['claim_id']}: "
            f"{decision['previous_status']} -> "
            f"{decision['new_status']}"
        )

        print(
            f"  Reason: "
            f"{decision['event_reason']}"
        )


def print_duplicate_audit() -> None:
    """
    Print duplicate decisions from PostgreSQL audit history.
    """
    decisions = fetch_duplicate_decisions()

    print("\nDuplicate Check Audit History")
    print("-----------------------------")

    if not decisions:
        print(
            "No duplicate decisions were recorded."
        )
        return

    for decision in decisions:
        print(
            f"{decision['claim_id']}: "
            f"{decision['previous_status']} -> "
            f"{decision['new_status']}"
        )

        print(
            f"  Reason: "
            f"{decision['event_reason']}"
        )


def main() -> None:
    """
    Run the Day 5 claims workflow.
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

    print(
        "Workflow tables reset successfully."
    )

    active_diagnosis_codes = (
        build_active_diagnosis_codes(
            project_data["diagnosis_codes"]
        )
    )

    member_index = build_member_index(
        project_data["members"]
    )

    print(
        "\nProcessing claims through intake, "
        "validation, eligibility, and "
        "duplicate detection..."
    )

    results = process_claim_batch(
        claims=project_data["claims"],
        active_diagnosis_codes=(
            active_diagnosis_codes
        ),
        member_index=member_index,
    )

    print_claim_results(
        results
    )

    print_result_totals(
        results
    )

    print_database_summary()

    print_validation_audit()

    print_eligibility_audit()

    print_duplicate_audit()

    print(
        "\nDay 5 workflow completed successfully."
    )


if __name__ == "__main__":
    main()