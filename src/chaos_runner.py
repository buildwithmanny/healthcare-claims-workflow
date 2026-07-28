import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.database import (
    fetch_claim_current_state,
    fetch_claim_history,
    fetch_manual_review_queue_items,
    fetch_retry_queue_items,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIRECTORY = PROJECT_ROOT / "reports"


@dataclass(frozen=True)
class ChaosScenario:
    """
    Expected outcome for one intentionally problematic claim.
    """

    scenario_name: str
    claim_id: str
    expected_final_status: str
    expected_retry_status: str | None
    expected_retry_count: int | None
    expected_manual_review_status: str | None
    required_status_path: tuple[str, ...]
    required_reason_fragments: tuple[str, ...]


@dataclass(frozen=True)
class ChaosScenarioResult:
    """
    Actual verification result for one chaos scenario.
    """

    scenario_name: str
    claim_id: str
    passed: bool

    expected_final_status: str
    actual_final_status: str | None

    expected_retry_status: str | None
    actual_retry_status: str | None

    expected_retry_count: int | None
    actual_retry_count: int | None

    expected_manual_review_status: str | None
    actual_manual_review_status: str | None

    checks: tuple[str, ...]
    failures: tuple[str, ...]


def require_text(
    record: dict[str, Any],
    field_name: str,
    scenario_name: str,
) -> str:
    """
    Read and validate a required text field.
    """
    value = str(
        record.get(
            field_name,
            "",
        )
    ).strip()

    if not value:
        raise ValueError(
            f"Chaos scenario '{scenario_name}' requires "
            f"field '{field_name}'."
        )

    return value


def optional_text(
    record: dict[str, Any],
    field_name: str,
) -> str | None:
    """
    Read an optional text field.
    """
    value = record.get(
        field_name
    )

    if value is None:
        return None

    cleaned_value = str(
        value
    ).strip()

    return cleaned_value or None


def optional_integer(
    record: dict[str, Any],
    field_name: str,
    scenario_name: str,
) -> int | None:
    """
    Read an optional nonnegative integer field.
    """
    value = record.get(
        field_name
    )

    if value is None:
        return None

    try:
        parsed_value = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"Chaos scenario '{scenario_name}' field "
            f"'{field_name}' must be an integer or null."
        ) from error

    if parsed_value < 0:
        raise ValueError(
            f"Chaos scenario '{scenario_name}' field "
            f"'{field_name}' cannot be negative."
        )

    return parsed_value


def require_string_list(
    record: dict[str, Any],
    field_name: str,
    scenario_name: str,
) -> tuple[str, ...]:
    """
    Validate a required list of nonblank strings.
    """
    values = record.get(
        field_name
    )

    if not isinstance(
        values,
        list,
    ):
        raise ValueError(
            f"Chaos scenario '{scenario_name}' field "
            f"'{field_name}' must be a list."
        )

    cleaned_values = tuple(
        str(value).strip()
        for value in values
        if str(value).strip()
    )

    if not cleaned_values:
        raise ValueError(
            f"Chaos scenario '{scenario_name}' field "
            f"'{field_name}' cannot be empty."
        )

    return cleaned_values


def build_chaos_scenarios(
    records: list[dict[str, Any]],
) -> list[ChaosScenario]:
    """
    Validate chaos-scenario configuration.
    """
    scenarios: list[ChaosScenario] = []

    seen_names: set[str] = set()
    seen_claim_ids: set[str] = set()

    for record in records:
        raw_name = str(
            record.get(
                "scenario_name",
                "",
            )
        ).strip()

        scenario_name = raw_name or "Unnamed scenario"

        claim_id = require_text(
            record,
            "claim_id",
            scenario_name,
        )

        expected_final_status = require_text(
            record,
            "expected_final_status",
            scenario_name,
        ).upper()

        if scenario_name in seen_names:
            raise ValueError(
                f"Duplicate chaos scenario name: "
                f"'{scenario_name}'."
            )

        if claim_id in seen_claim_ids:
            raise ValueError(
                "Each claim may appear only once in "
                f"chaos_scenarios.json. Duplicate: "
                f"'{claim_id}'."
            )

        seen_names.add(
            scenario_name
        )

        seen_claim_ids.add(
            claim_id
        )

        expected_retry_status = optional_text(
            record,
            "expected_retry_status",
        )

        if expected_retry_status is not None:
            expected_retry_status = (
                expected_retry_status.upper()
            )

        expected_manual_review_status = optional_text(
            record,
            "expected_manual_review_status",
        )

        if expected_manual_review_status is not None:
            expected_manual_review_status = (
                expected_manual_review_status.upper()
            )

        scenarios.append(
            ChaosScenario(
                scenario_name=scenario_name,
                claim_id=claim_id,
                expected_final_status=(
                    expected_final_status
                ),
                expected_retry_status=(
                    expected_retry_status
                ),
                expected_retry_count=(
                    optional_integer(
                        record,
                        "expected_retry_count",
                        scenario_name,
                    )
                ),
                expected_manual_review_status=(
                    expected_manual_review_status
                ),
                required_status_path=(
                    require_string_list(
                        record,
                        "required_status_path",
                        scenario_name,
                    )
                ),
                required_reason_fragments=(
                    require_string_list(
                        record,
                        "required_reason_fragments",
                        scenario_name,
                    )
                ),
            )
        )

    return scenarios


def build_latest_record_index(
    rows: list[dict[str, Any]],
    id_field: str,
) -> dict[str, dict[str, Any]]:
    """
    Index the latest queue record for each claim.
    """
    index: dict[
        str,
        dict[str, Any],
    ] = {}

    for row in rows:
        claim_id = str(
            row["claim_id"]
        )

        existing_row = index.get(
            claim_id
        )

        if existing_row is None:
            index[claim_id] = row
            continue

        if int(
            row[id_field]
        ) > int(
            existing_row[id_field]
        ):
            index[claim_id] = row

    return index


def contains_ordered_subsequence(
    actual_values: list[str],
    required_values: tuple[str, ...],
) -> bool:
    """
    Return whether required values appear in the supplied order.

    Other values may appear between required values.
    """
    required_position = 0

    for actual_value in actual_values:
        if required_position >= len(
            required_values
        ):
            break

        if (
            actual_value
            == required_values[
                required_position
            ]
        ):
            required_position += 1

    return required_position == len(
        required_values
    )


def evaluate_chaos_scenarios(
    scenarios: list[ChaosScenario],
) -> list[ChaosScenarioResult]:
    """
    Compare every configured scenario with persisted workflow data.
    """
    retry_index = build_latest_record_index(
        fetch_retry_queue_items(),
        "retry_id",
    )

    manual_review_index = (
        build_latest_record_index(
            fetch_manual_review_queue_items(),
            "review_id",
        )
    )

    results: list[ChaosScenarioResult] = []

    for scenario in scenarios:
        checks: list[str] = []
        failures: list[str] = []

        current_state = fetch_claim_current_state(
            scenario.claim_id
        )

        history = fetch_claim_history(
            scenario.claim_id
        )

        retry_item = retry_index.get(
            scenario.claim_id
        )

        manual_review_item = (
            manual_review_index.get(
                scenario.claim_id
            )
        )

        actual_final_status = (
            str(
                current_state[
                    "current_status"
                ]
            )
            if current_state is not None
            else None
        )

        actual_retry_status = (
            str(
                retry_item[
                    "retry_status"
                ]
            )
            if retry_item is not None
            else None
        )

        actual_retry_count = (
            int(
                retry_item[
                    "retry_count"
                ]
            )
            if retry_item is not None
            else None
        )

        actual_manual_review_status = (
            str(
                manual_review_item[
                    "review_status"
                ]
            )
            if manual_review_item is not None
            else None
        )

        if current_state is None:
            failures.append(
                "Claim does not exist in PostgreSQL."
            )

        elif (
            actual_final_status
            != scenario.expected_final_status
        ):
            failures.append(
                "Final status mismatch: expected "
                f"{scenario.expected_final_status}, "
                f"found {actual_final_status}."
            )

        else:
            checks.append(
                "Final claim status matched."
            )

        if not history:
            failures.append(
                "No audit history was recorded."
            )

        else:
            incomplete_events = [
                event
                for event in history
                if (
                    not str(
                        event.get(
                            "processing_step",
                            "",
                        )
                    ).strip()
                    or not str(
                        event.get(
                            "event_reason",
                            "",
                        )
                    ).strip()
                    or event.get(
                        "created_at"
                    )
                    is None
                )
            ]

            if incomplete_events:
                failures.append(
                    "One or more audit events were missing "
                    "a processing step, reason, or timestamp."
                )

            else:
                checks.append(
                    "Every audit event contained a step, "
                    "reason, and timestamp."
                )

        actual_status_path = [
            str(
                event["new_status"]
            )
            for event in history
        ]

        if contains_ordered_subsequence(
            actual_status_path,
            scenario.required_status_path,
        ):
            checks.append(
                "Required state path was present."
            )

        else:
            failures.append(
                "Required state path was not found. "
                f"Required: "
                f"{list(scenario.required_status_path)}. "
                f"Actual: {actual_status_path}."
            )

        combined_reasons = " ".join(
            str(
                event.get(
                    "event_reason",
                    "",
                )
            )
            for event in history
        ).lower()

        missing_reason_fragments = [
            fragment
            for fragment
            in scenario.required_reason_fragments
            if fragment.lower()
            not in combined_reasons
        ]

        if missing_reason_fragments:
            failures.append(
                "Missing expected audit reason text: "
                f"{missing_reason_fragments}."
            )

        else:
            checks.append(
                "Required audit reasons were present."
            )

        if scenario.expected_retry_status is None:
            if retry_item is None:
                checks.append(
                    "No retry record was expected or created."
                )

            else:
                failures.append(
                    "Unexpected retry record found with "
                    f"status {actual_retry_status}."
                )

        elif retry_item is None:
            failures.append(
                "Expected retry record was not created."
            )

        else:
            if (
                actual_retry_status
                == scenario.expected_retry_status
            ):
                checks.append(
                    "Retry status matched."
                )

            else:
                failures.append(
                    "Retry status mismatch: expected "
                    f"{scenario.expected_retry_status}, "
                    f"found {actual_retry_status}."
                )

            if (
                actual_retry_count
                == scenario.expected_retry_count
            ):
                checks.append(
                    "Retry count matched."
                )

            else:
                failures.append(
                    "Retry count mismatch: expected "
                    f"{scenario.expected_retry_count}, "
                    f"found {actual_retry_count}."
                )

        if (
            scenario.expected_manual_review_status
            is None
        ):
            if manual_review_item is None:
                checks.append(
                    "No manual-review record was expected "
                    "or created."
                )

            else:
                failures.append(
                    "Unexpected manual-review record found "
                    f"with status "
                    f"{actual_manual_review_status}."
                )

        elif manual_review_item is None:
            failures.append(
                "Expected manual-review record was not created."
            )

        elif (
            actual_manual_review_status
            == scenario.expected_manual_review_status
        ):
            checks.append(
                "Manual-review status matched."
            )

        else:
            failures.append(
                "Manual-review status mismatch: expected "
                f"{scenario.expected_manual_review_status}, "
                f"found "
                f"{actual_manual_review_status}."
            )

        results.append(
            ChaosScenarioResult(
                scenario_name=(
                    scenario.scenario_name
                ),
                claim_id=scenario.claim_id,
                passed=not failures,
                expected_final_status=(
                    scenario.expected_final_status
                ),
                actual_final_status=(
                    actual_final_status
                ),
                expected_retry_status=(
                    scenario.expected_retry_status
                ),
                actual_retry_status=(
                    actual_retry_status
                ),
                expected_retry_count=(
                    scenario.expected_retry_count
                ),
                actual_retry_count=(
                    actual_retry_count
                ),
                expected_manual_review_status=(
                    scenario
                    .expected_manual_review_status
                ),
                actual_manual_review_status=(
                    actual_manual_review_status
                ),
                checks=tuple(
                    checks
                ),
                failures=tuple(
                    failures
                ),
            )
        )

    return results


def write_chaos_report(
    results: list[ChaosScenarioResult],
) -> Path:
    """
    Write chaos-scenario verification results as JSON.
    """
    REPORTS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        REPORTS_DIRECTORY
        / "chaos_scenario_report.json"
    )

    passed_count = sum(
        1
        for result in results
        if result.passed
    )

    failed_count = (
        len(results)
        - passed_count
    )

    report = {
        "generated_at_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "scenario_count": len(
            results
        ),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "all_scenarios_controlled": (
            failed_count == 0
        ),
        "scenarios": [
            asdict(
                result
            )
            for result in results
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


def assert_all_scenarios_controlled(
    results: list[ChaosScenarioResult],
) -> None:
    """
    Fail the run when any chaos scenario behaves unexpectedly.
    """
    failed_results = [
        result
        for result in results
        if not result.passed
    ]

    if not failed_results:
        return

    failure_lines: list[str] = []

    for result in failed_results:
        failure_lines.append(
            f"{result.claim_id} — "
            f"{result.scenario_name}: "
            f"{'; '.join(result.failures)}"
        )

    raise RuntimeError(
        "One or more chaos scenarios did not reach "
        "their controlled outcomes:\n"
        + "\n".join(
            failure_lines
        )
    )