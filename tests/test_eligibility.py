from src.eligibility import (
    build_member_index,
    evaluate_eligibility,
)


def test_active_member_with_coverage_is_eligible(
    valid_claim,
    member_records,
):
    member_index = build_member_index(
        member_records
    )

    decision = evaluate_eligibility(
        valid_claim,
        member_index,
    )

    assert decision.is_eligible is True


def test_expired_coverage_is_ineligible(
    valid_claim,
    member_records,
):
    claim = valid_claim.copy()
    claim["member_id"] = "M002"
    claim["service_date"] = "2026-07-05"

    member_index = build_member_index(
        member_records
    )

    decision = evaluate_eligibility(
        claim,
        member_index,
    )

    assert decision.is_eligible is False
    assert "coverage was not active" in decision.reason


def test_unknown_member_is_ineligible(
    valid_claim,
    member_records,
):
    claim = valid_claim.copy()
    claim["member_id"] = "M999"

    member_index = build_member_index(
        member_records
    )

    decision = evaluate_eligibility(
        claim,
        member_index,
    )

    assert decision.is_eligible is False
    assert "was not found" in decision.reason