import pytest

from src.fraud_review import (
    FraudReviewRules,
    build_fraud_review_rules,
)
from src.pricing import (
    build_pricing_rule_index,
)


@pytest.fixture
def valid_claim() -> dict[str, str]:
    """
    Return one structurally valid synthetic claim.
    """
    return {
        "claim_id": "TEST001",
        "member_id": "M001",
        "provider_id": "PRV001",
        "diagnosis_code": "DX001",
        "procedure_code": "PROC1001",
        "service_date": "2026-07-01",
        "billed_amount": "180.00",
        "submitted_date": "2026-07-02",
    }


@pytest.fixture
def active_diagnosis_codes() -> set[str]:
    """
    Return valid active diagnosis codes.
    """
    return {
        "DX001",
        "DX002",
    }


@pytest.fixture
def member_records() -> list[dict[str, str]]:
    """
    Return active and expired synthetic member records.
    """
    return [
        {
            "member_id": "M001",
            "first_name": "Avery",
            "last_name": "Carter",
            "date_of_birth": "1988-04-12",
            "plan_id": "PLAN001",
            "coverage_start": "2026-01-01",
            "coverage_end": "2026-12-31",
            "member_status": "ACTIVE",
        },
        {
            "member_id": "M002",
            "first_name": "Taylor",
            "last_name": "Morgan",
            "date_of_birth": "1992-02-15",
            "plan_id": "PLAN002",
            "coverage_start": "2026-01-01",
            "coverage_end": "2026-06-30",
            "member_status": "ACTIVE",
        },
    ]


@pytest.fixture
def pricing_rule_index() -> dict:
    """
    Return pricing rules for success and retry tests.
    """
    return build_pricing_rule_index(
        [
            {
                "procedure_code": "PROC1001",
                "allowed_amount": 150.00,
                "pricing_method": "STANDARD",
                "temporary_failures_before_success": 0,
            },
            {
                "procedure_code": "PROC1005",
                "allowed_amount": 500.00,
                "pricing_method": (
                    "SIMULATED_EXTERNAL_SERVICE"
                ),
                "temporary_failures_before_success": 1,
            },
        ]
    )


@pytest.fixture
def fraud_review_rules() -> FraudReviewRules:
    """
    Return rules that allow the normal happy-path claim.
    """
    return build_fraud_review_rules(
        {
            "high_billed_amount": {
                "threshold": 1000.00,
            },
            "high_claim_frequency": {
                "max_claims_per_member": 10,
                "period_days": 30,
            },
            "manual_review_procedure_codes": {
                "procedure_codes": [
                    "PROC1007",
                ],
            },
        }
    )