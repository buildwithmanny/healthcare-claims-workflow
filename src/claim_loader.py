import csv
import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIRECTORY = PROJECT_ROOT / "data"


def load_csv(filename: str) -> list[dict[str, str]]:
    """
    Load a CSV file from the project data directory.

    Args:
        filename: Name of the CSV file.

    Returns:
        A list of dictionaries representing the CSV rows.

    Raises:
        FileNotFoundError: If the requested file does not exist.
        ValueError: If the CSV file does not contain headers.
    """
    file_path = DATA_DIRECTORY / filename

    if not file_path.exists():
        raise FileNotFoundError(
            f"Required CSV file was not found: {file_path}"
        )

    with file_path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError(
                f"CSV file '{filename}' does not contain headers."
            )

        return list(reader)


def load_json(filename: str) -> Any:
    """
    Load a JSON file from the project data directory.

    Args:
        filename: Name of the JSON file.

    Returns:
        Parsed JSON content.

    Raises:
        FileNotFoundError: If the requested file does not exist.
        ValueError: If the JSON file contains invalid JSON.
    """
    file_path = DATA_DIRECTORY / filename

    if not file_path.exists():
        raise FileNotFoundError(
            f"Required JSON file was not found: {file_path}"
        )

    try:
        with file_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    except JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in '{filename}'. "
            f"Check line {error.lineno}, "
            f"column {error.colno}."
        ) from error


def load_claims() -> list[dict[str, str]]:
    """
    Load incoming synthetic claims.
    """
    return load_csv("claims.csv")


def load_members() -> list[dict[str, str]]:
    """
    Load synthetic member records.
    """
    return load_csv("members.csv")


def load_diagnosis_codes() -> list[dict[str, str]]:
    """
    Load the synthetic diagnosis-code reference data.
    """
    return load_csv("diagnosis_codes.csv")


def load_pricing_rules() -> list[dict[str, Any]]:
    """
    Load synthetic pricing rules.
    """
    return load_json("pricing_rules.json")


def load_review_rules() -> dict[str, Any]:
    """
    Load synthetic fraud and business-review rules.
    """
    return load_json("review_rules.json")


def load_manual_review_decisions() -> list[dict[str, Any]]:
    """
    Load synthetic reviewer decisions.
    """
    return load_json(
        "manual_review_decisions.json"
    )


def load_chaos_scenarios() -> list[dict[str, Any]]:
    """
    Load expected outcomes for controlled chaos scenarios.
    """
    return load_json(
        "chaos_scenarios.json"
    )


def load_project_data() -> dict[str, Any]:
    """
    Load every synthetic data source required by the workflow.

    Returns:
        A dictionary containing all project datasets.
    """
    return {
        "claims": load_claims(),
        "members": load_members(),
        "diagnosis_codes": load_diagnosis_codes(),
        "pricing_rules": load_pricing_rules(),
        "review_rules": load_review_rules(),
        "manual_review_decisions": (
            load_manual_review_decisions()
        ),
        "chaos_scenarios": load_chaos_scenarios(),
    }


def print_source_summary(
    project_data: dict[str, Any],
) -> None:
    """
    Print a record count for every loaded project source.
    """
    print("\nSource File Summary")
    print("-------------------")

    for source_name, source_data in project_data.items():
        if isinstance(
            source_data,
            list,
        ):
            print(
                f"{source_name}: "
                f"{len(source_data)} records loaded"
            )

        elif isinstance(
            source_data,
            dict,
        ):
            print(
                f"{source_name}: "
                f"{len(source_data)} rule groups loaded"
            )

        else:
            print(
                f"{source_name}: loaded"
            )