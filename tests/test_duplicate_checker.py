from src.duplicate_checker import (
    build_duplicate_signature,
    evaluate_duplicate,
)


def test_duplicate_claim_is_routed_to_duplicate(
    valid_claim,
):
    decision = evaluate_duplicate(
        claim=valid_claim,
        matched_claim_id="CLM001",
    )

    assert decision.is_duplicate is True
    assert decision.matched_claim_id == "CLM001"
    assert "matched prior claim" in decision.reason


def test_unique_claim_continues_processing(
    valid_claim,
):
    decision = evaluate_duplicate(
        claim=valid_claim,
        matched_claim_id=None,
    )

    assert decision.is_duplicate is False
    assert decision.matched_claim_id is None


def test_duplicate_signature_uses_expected_fields(
    valid_claim,
):
    signature = build_duplicate_signature(
        valid_claim
    )

    assert signature == (
        "M001",
        "PRV001",
        "PROC1001",
        "2026-07-01",
    )