from collections import Counter
from pathlib import Path
from typing import Any

from src.claim_loader import (
    load_project_data,
    print_source_summary,
)
from src.database import (
    fetch_claim_current_state,
    fetch_claim_history,
    fetch_claim_status_summary,
    fetch_duplicate_decisions,
    fetch_eligibility_decisions,
    fetch_fraud_review_decisions,
    fetch_priced_claims,
    fetch_pricing_decisions,
    fetch_retry_queue_items,
    fetch_validation_failures,
    reset_workflow_data,
    test_connection,
)
from src.eligibility import (
    build_member_index,
)
from src.fraud_review import (
    build_fraud_review_rules,
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
    process_retry_queue,
)


def print_claim_results(
    results: list[ClaimWorkflowResult],
) -> None:
    """
    Print the final outcome for every claim.
    """
    print("\nFinal Claim Workflow Results")
    print("----------------------------")

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

        if result.pricing_outcome is not None:
            print(
                f"  Pricing outcome: "
                f"{result.pricing_outcome.value}"
            )

        if result.pricing_reason is not None:
            print(
                f"  Pricing: "
                f"{result.pricing_reason}"
            )

        if result.allowed_amount is not None:
            print(
                f"  Allowed amount: "
                f"${result.allowed_amount:,.2f}"
            )

        if result.fraud_review_outcome is not None:
            print(
                f"  Fraud review outcome: "
                f"{result.fraud_review_outcome.value}"
            )

        if result.fraud_review_reason is not None:
            print(
                f"  Fraud review: "
                f"{result.fraud_review_reason}"
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

        if result.retry_reason is not None:
            print(
                f"  Retry result: "
                f"{result.retry_reason}"
            )


def print_result_totals(
    results: list[ClaimWorkflowResult],
) -> None:
    """
    Print final-status totals.
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
    Print current PostgreSQL status totals.
    """
    summary = fetch_claim_status_summary()

    print("\nPostgreSQL Status Summary")
    print("-------------------------")

    for row in summary:
        print(
            f"{row['current_status']}: "
            f"{row['claim_count']}"
        )


def print_audit_section(
    title: str,
    decisions: list[dict[str, Any]],
) -> None:
    """
    Print one collection of workflow audit events.
    """
    print(
        f"\n{title}"
    )

    print(
        "-" * len(
            title
        )
    )

    if not decisions:
        print(
            "No matching audit events were recorded."
        )
        return

    for decision in decisions:
        print(
            f"{decision['claim_id']}: "
            f"{decision['previous_status']} -> "
            f"{decision['new_status']}"
        )

        if decision.get(
            "retry_attempt"
        ) is not None:
            print(
                f"  Retry attempt: "
                f"{decision['retry_attempt']}"
            )

        print(
            f"  Reason: "
            f"{decision['event_reason']}"
        )


def print_priced_claims() -> None:
    """
    Print claims that received successful pricing.
    """
    claims = fetch_priced_claims()

    print("\nSuccessfully Priced Claims")
    print("--------------------------")

    if not claims:
        print(
            "No claims received an allowed amount."
        )
        return

    for claim in claims:
        print(
            f"{claim['claim_id']}: "
            f"{claim['procedure_code']}"
        )

        print(
            f"  Billed amount: "
            f"${claim['billed_amount']:,.2f}"
        )

        print(
            f"  Allowed amount: "
            f"${claim['allowed_amount']:,.2f}"
        )

        print(
            f"  Current status: "
            f"{claim['current_status']}"
        )


def print_retry_queue() -> None:
    """
    Print retry counts, limits, errors, and final outcomes.
    """
    retry_items = fetch_retry_queue_items()

    print("\nRetry Queue Final State")
    print("-----------------------")

    if not retry_items:
        print(
            "No retry queue records were created."
        )
        return

    for item in retry_items:
        print(
            f"{item['claim_id']}: "
            f"{item['retry_status']}"
        )

        print(
            f"  Failed step: "
            f"{item['failed_step']}"
        )

        print(
            f"  Retry count: "
            f"{item['retry_count']}"
        )

        print(
            f"  Maximum retries: "
            f"{item['max_retries']}"
        )

        if item["last_error"] is not None:
            print(
                f"  Last error: "
                f"{item['last_error']}"
            )


def print_generated_reports(
    report_paths: dict[str, Path],
) -> None:
    """
    Print all generated report locations.
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


def print_invalid_transition_guard() -> None:
    """
    Demonstrate that a validation failure cannot move to pricing.
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
            "Blocked invalid transition as expected."
        )

        print(
            f"  {error}"
        )

        return

    raise RuntimeError(
        "The state manager unexpectedly allowed "
        "VALIDATION_FAILED -> PRICING."
    )


def print_claim_journey(
    claim_id: str,
) -> None:
    """
    Print the current state and complete audit history for one claim.
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
        "Where is this claim now?"
    )

    print(
        f"  Current status: "
        f"{current_state['current_status']}"
    )

    print(
        f"  Current record last updated: "
        f"{current_state['updated_at']}"
    )

    print(
        "\nWhere has this claim been?"
    )

    if not history:
        print(
            "  No audit events were found."
        )
        return

    for event in history:
        previous_status = (
            event["previous_status"]
            if event["previous_status"] is not None
            else "START"
        )

        print(
            f"  Event {event['event_id']}: "
            f"{previous_status} -> "
            f"{event['new_status']}"
        )

        print(
            f"    Processing step: "
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


def merge_retry_results(
    initial_results: list[ClaimWorkflowResult],
    retry_results: dict[str, ClaimWorkflowResult],
) -> list[ClaimWorkflowResult]:
    """
    Replace temporary initial results with their final retry outcomes.
    """
    return [
        retry_results.get(
            result.claim_id,
            result,
        )
        for result in initial_results
    ]


def main() -> None:
    """
    Run the Day 9 healthcare claims workflow.
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

    pricing_rule_index = build_pricing_rule_index(
        project_data["pricing_rules"]
    )

    fraud_review_rules = build_fraud_review_rules(
        project_data["review_rules"]
    )

    print(
        "\nPhase 1: Processing initial claim attempts..."
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
        "\nPhase 2: Processing the retry queue..."
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

    final_results = merge_retry_results(
        initial_results=initial_results,
        retry_results=retry_results,
    )

    report_paths = generate_reports()

    print_claim_results(
        final_results
    )

    print_result_totals(
        final_results
    )

    print_database_summary()

    print_retry_queue()

    print_audit_section(
        "Validation Failure Audit History",
        fetch_validation_failures(),
    )

    print_audit_section(
        "Eligibility Audit History",
        fetch_eligibility_decisions(),
    )

    print_audit_section(
        "Duplicate Check Audit History",
        fetch_duplicate_decisions(),
    )

    print_audit_section(
        "Pricing and Retry Audit History",
        fetch_pricing_decisions(),
    )

    print_audit_section(
        "Fraud Review Audit History",
        fetch_fraud_review_decisions(),
    )

    print_priced_claims()

    print_invalid_transition_guard()

    print_claim_journey(
        "CLM015"
    )

    print_claim_journey(
        "CLM017"
    )

    print_generated_reports(
        report_paths
    )

    print(
        "\nDay 9 workflow completed successfully."
    )


if __name__ == "__main__":
    main()