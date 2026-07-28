from collections import Counter
from pathlib import Path
from typing import Any

from src.chaos_runner import (
    ChaosScenarioResult,
    assert_all_scenarios_controlled,
    build_chaos_scenarios,
    evaluate_chaos_scenarios,
    write_chaos_report,
)
from src.claim_loader import (
    load_project_data,
    print_source_summary,
)
from src.database import (
    fetch_claim_current_state,
    fetch_claim_history,
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
from src.state_manager import (
    ClaimStatus,
    InvalidStateTransitionError,
    validate_transition,
)
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
    Print the final status and major operational outcomes.
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


def print_result_totals(
    results: list[ClaimWorkflowResult],
) -> None:
    """
    Print final-status totals from in-memory workflow results.
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
            f"  Failed step: "
            f"{row['failed_step']}"
        )

        print(
            f"  Retry count: "
            f"{row['retry_count']} of "
            f"{row['max_retries']}"
        )

        if row["last_error"] is not None:
            print(
                f"  Last error: "
                f"{row['last_error']}"
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

        if row["reviewer_notes"] is not None:
            print(
                f"  Reviewer notes: "
                f"{row['reviewer_notes']}"
            )


def print_chaos_results(
    results: list[ChaosScenarioResult],
) -> None:
    """
    Print the controlled-outcome verification matrix.
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

        print(
            f"  Final status: "
            f"{result.actual_final_status}"
        )

        if result.actual_retry_status is not None:
            print(
                f"  Retry: "
                f"{result.actual_retry_status} "
                f"({result.actual_retry_count} attempts)"
            )

        if (
            result.actual_manual_review_status
            is not None
        ):
            print(
                f"  Manual review: "
                f"{result.actual_manual_review_status}"
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


def print_claim_journey(
    claim_id: str,
) -> None:
    """
    Print current state and complete audit history for one claim.
    """
    current_state = fetch_claim_current_state(
        claim_id
    )

    history = fetch_claim_history(
        claim_id
    )

    title = f"Claim Journey — {claim_id}"

    print(
        f"\n{title}"
    )

    print(
        "-" * len(
            title
        )
    )

    if current_state is None:
        print(
            "Claim was not found."
        )
        return

    print(
        f"Current status: "
        f"{current_state['current_status']}"
    )

    for event in history:
        previous_status = (
            event["previous_status"]
            if event["previous_status"] is not None
            else "START"
        )

        print(
            f"  {previous_status} -> "
            f"{event['new_status']}"
        )

        print(
            f"    Step: "
            f"{event['processing_step']}"
        )

        if event["retry_attempt"] is not None:
            print(
                f"    Retry attempt: "
                f"{event['retry_attempt']}"
            )

        print(
            f"    Why: "
            f"{event['event_reason']}"
        )

        print(
            f"    When: "
            f"{event['created_at']}"
        )


def print_invalid_transition_guard() -> None:
    """
    Confirm that a failed validation cannot jump into pricing.
    """
    print("\nInvalid Transition Guard")
    print("------------------------")

    try:
        validate_transition(
            ClaimStatus.VALIDATION_FAILED,
            ClaimStatus.PRICING,
        )

    except InvalidStateTransitionError as error:
        print(
            "PASS | Invalid transition was blocked."
        )

        print(
            f"  {error}"
        )

        return

    raise RuntimeError(
        "VALIDATION_FAILED -> PRICING "
        "was unexpectedly allowed."
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


def main() -> None:
    """
    Run the Day 11 controlled-chaos workflow.
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
        "\nPhase 1: Running initial claim processing..."
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
        "\nPhase 2: Running retry processing..."
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
        "\nPhase 3: Running manual-review processing..."
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

    print_invalid_transition_guard()

    print_claim_journey(
        "CLM015"
    )

    print_claim_journey(
        "CLM017"
    )

    print_claim_journey(
        "CLM018"
    )

    print_generated_reports(
        report_paths
    )

    assert_all_scenarios_controlled(
        chaos_results
    )

    print(
        "\nDay 11 completed successfully."
    )

    print(
        "Every configured chaos scenario reached "
        "its controlled outcome."
    )


if __name__ == "__main__":
    main()