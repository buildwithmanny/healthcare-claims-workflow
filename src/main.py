from collections import Counter
from pathlib import Path

from src.chaos_runner import (
    ChaosScenarioResult,
    build_chaos_scenarios,
    evaluate_chaos_scenarios,
    write_chaos_report,
)
from src.claim_loader import (
    load_project_data,
    print_source_summary,
)
from src.database import (
    fetch_claim_status_summary,
    fetch_manual_review_queue_items,
    fetch_retry_queue_items,
    reset_workflow_data,
    test_connection,
)
from src.eligibility import (
    build_member_index,
)
from src.fraud_review import (
    build_fraud_review_rules,
)
from src.manual_review import (
    build_manual_review_decision_index,
)
from src.pricing import (
    build_pricing_rule_index,
)
from src.reporting import generate_reports
from src.validator import (
    build_active_diagnosis_codes,
)
from src.workflow_engine import (
    ClaimWorkflowResult,
    process_claim_batch,
    process_manual_review_queue,
    process_retry_queue,
)


def merge_result_overrides(
    base_results: list[ClaimWorkflowResult],
    overrides: dict[
        str,
        ClaimWorkflowResult,
    ],
) -> list[ClaimWorkflowResult]:
    """
    Replace earlier results with later queue outcomes.
    """
    return [
        overrides.get(
            result.claim_id,
            result,
        )
        for result in base_results
    ]


def print_final_results(
    results: list[ClaimWorkflowResult],
) -> None:
    """
    Print the final claim statuses and major operational outcomes.
    """
    print("\nFinal Claim Results")
    print("-------------------")

    for result in results:
        print(
            f"{result.claim_id}: "
            f"{result.final_status.value}"
        )

        if result.validation_errors:
            print(
                "  Validation errors: "
                + "; ".join(
                    result.validation_errors
                )
            )

        if result.duplicate_of_claim_id is not None:
            print(
                f"  Duplicate of: "
                f"{result.duplicate_of_claim_id}"
            )

        if result.pricing_outcome is not None:
            print(
                f"  Pricing outcome: "
                f"{result.pricing_outcome.value}"
            )

        if result.allowed_amount is not None:
            print(
                f"  Allowed amount: "
                f"${result.allowed_amount:,.2f}"
            )

        if result.retry_status is not None:
            print(
                f"  Retry status: "
                f"{result.retry_status.value}"
            )

            print(
                f"  Retry attempts: "
                f"{result.retry_count}"
            )

        if result.manual_review_status is not None:
            print(
                f"  Manual review: "
                f"{result.manual_review_status.value}"
            )

        if result.reviewer_notes is not None:
            print(
                f"  Reviewer notes: "
                f"{result.reviewer_notes}"
            )

        if result.processing_error is not None:
            print(
                f"  Processing error: "
                f"{result.processing_error}"
            )

            print(
                "  Failure persisted: "
                f"{result.failure_persisted}"
            )


def print_result_totals(
    results: list[ClaimWorkflowResult],
) -> None:
    """
    Print final-status totals from in-memory results.
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
    Print final-status totals stored in PostgreSQL.
    """
    rows = fetch_claim_status_summary()

    print("\nPostgreSQL Status Summary")
    print("-------------------------")

    for row in rows:
        print(
            f"{row['current_status']}: "
            f"{row['claim_count']}"
        )


def print_retry_queue() -> None:
    """
    Print retry queue outcomes.
    """
    rows = fetch_retry_queue_items()

    print("\nRetry Queue Outcomes")
    print("--------------------")

    if not rows:
        print(
            "No retry records were created."
        )
        return

    for row in rows:
        print(
            f"{row['claim_id']}: "
            f"{row['retry_status']}"
        )

        print(
            f"  Retry count: "
            f"{row['retry_count']} of "
            f"{row['max_retries']}"
        )


def print_manual_review_queue() -> None:
    """
    Print manual-review queue outcomes.
    """
    rows = fetch_manual_review_queue_items()

    print("\nManual Review Outcomes")
    print("----------------------")

    if not rows:
        print(
            "No manual-review records were created."
        )
        return

    for row in rows:
        print(
            f"{row['claim_id']}: "
            f"{row['review_status']}"
        )

        print(
            f"  Reason: "
            f"{row['review_reason']}"
        )


def print_chaos_results(
    results: list[ChaosScenarioResult],
) -> None:
    """
    Print controlled-outcome verification results.
    """
    print("\nChaos Scenario Verification")
    print("---------------------------")

    for result in results:
        outcome = (
            "PASS"
            if result.passed
            else "FAIL"
        )

        print(
            f"{outcome} | "
            f"{result.claim_id} | "
            f"{result.scenario_name}"
        )

        for failure in result.failures:
            print(
                f"  Failure: {failure}"
            )

    passed_count = sum(
        1
        for result in results
        if result.passed
    )

    print(
        "\nControlled scenarios: "
        f"{passed_count} of {len(results)}"
    )


def print_processing_errors(
    results: list[ClaimWorkflowResult],
) -> int:
    """
    Print unexpected claim-level failures.

    Returns:
        Number of unexpected processing failures.
    """
    failed_results = [
        result
        for result in results
        if result.processing_error is not None
    ]

    print("\nUnexpected Processing Errors")
    print("----------------------------")

    if not failed_results:
        print(
            "No unexpected claim-processing errors occurred."
        )
        return 0

    for result in failed_results:
        print(
            f"{result.claim_id}: "
            f"{result.processing_error}"
        )

        print(
            "  Persisted as FAILED: "
            f"{result.failure_persisted}"
        )

    return len(
        failed_results
    )


def print_generated_reports(
    report_paths: dict[str, Path],
) -> None:
    """
    Print generated report locations.
    """
    print("\nGenerated Reports")
    print("-----------------")

    for report_name, report_path in (
        report_paths.items()
    ):
        print(
            f"{report_name}: "
            f"{report_path}"
        )


def run_application() -> int:
    """
    Run the complete Day 12 workflow.

    Returns:
        0 when all claims and scenario checks complete successfully.
        1 when unexpected claim failures or scenario failures occur.
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

    print("\nResetting local workflow data...")

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

    pricing_rule_index = build_pricing_rule_index(
        project_data["pricing_rules"]
    )

    fraud_review_rules = build_fraud_review_rules(
        project_data["review_rules"]
    )

    manual_review_decision_index = (
        build_manual_review_decision_index(
            project_data[
                "manual_review_decisions"
            ]
        )
    )

    chaos_scenarios = build_chaos_scenarios(
        project_data["chaos_scenarios"]
    )

    print(
        "\nPhase 1: Running isolated claim processing..."
    )

    initial_results = process_claim_batch(
        claims=project_data["claims"],
        active_diagnosis_codes=(
            active_diagnosis_codes
        ),
        member_index=member_index,
        pricing_rule_index=(
            pricing_rule_index
        ),
        fraud_review_rules=(
            fraud_review_rules
        ),
    )

    print(
        "\nPhase 2: Running isolated retry processing..."
    )

    retry_results = process_retry_queue(
        claims=project_data["claims"],
        initial_results=initial_results,
        pricing_rule_index=(
            pricing_rule_index
        ),
        fraud_review_rules=(
            fraud_review_rules
        ),
    )

    post_retry_results = (
        merge_result_overrides(
            base_results=initial_results,
            overrides=retry_results,
        )
    )

    print(
        "\nPhase 3: Running isolated "
        "manual-review processing..."
    )

    manual_review_results = (
        process_manual_review_queue(
            current_results=post_retry_results,
            decision_index=(
                manual_review_decision_index
            ),
        )
    )

    final_results = merge_result_overrides(
        base_results=post_retry_results,
        overrides=manual_review_results,
    )

    print(
        "\nPhase 4: Verifying controlled outcomes..."
    )

    chaos_results = evaluate_chaos_scenarios(
        chaos_scenarios
    )

    report_paths = generate_reports()

    chaos_report_path = write_chaos_report(
        chaos_results
    )

    report_paths[
        "chaos_scenario_report"
    ] = chaos_report_path

    print_final_results(
        final_results
    )

    print_result_totals(
        final_results
    )

    print_database_summary()

    print_retry_queue()

    print_manual_review_queue()

    print_chaos_results(
        chaos_results
    )

    processing_error_count = (
        print_processing_errors(
            final_results
        )
    )

    print_generated_reports(
        report_paths
    )

    chaos_failure_count = sum(
        1
        for result in chaos_results
        if not result.passed
    )

    if (
        processing_error_count > 0
        or chaos_failure_count > 0
    ):
        print(
            "\nDay 12 completed with controlled errors."
        )

        print(
            "The remaining claims continued processing, "
            "but review the failure output above."
        )

        return 1

    print(
        "\nDay 12 workflow completed successfully."
    )

    print(
        "All claims were isolated, all configured "
        "scenarios were controlled, and no unexpected "
        "error stopped the batch."
    )

    return 0


def main() -> int:
    """
    Application boundary with clear top-level error handling.
    """
    try:
        return run_application()

    except FileNotFoundError as error:
        print(
            "\nApplication configuration error"
        )

        print(
            "A required project file could not be found."
        )

        print(
            f"Details: {error}"
        )

        return 1

    except ValueError as error:
        print(
            "\nApplication data or configuration error"
        )

        print(
            f"Details: {error}"
        )

        return 1

    except Exception as error:
        print(
            "\nUnexpected application-level failure"
        )

        print(
            "Claim-level failures are isolated, but the "
            "application encountered a broader system error."
        )

        print(
            f"Error type: "
            f"{type(error).__name__}"
        )

        print(
            f"Details: {error}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )