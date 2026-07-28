from src.validator import validate_claim


def test_valid_claim_has_no_validation_errors(
    valid_claim,
    active_diagnosis_codes,
):
    errors = validate_claim(
        valid_claim,
        active_diagnosis_codes,
    )

    assert errors == []


def test_missing_member_id_fails_validation(
    valid_claim,
    active_diagnosis_codes,
):
    claim = valid_claim.copy()
    claim["member_id"] = ""

    errors = validate_claim(
        claim,
        active_diagnosis_codes,
    )

    assert "member_id is required." in errors


def test_invalid_diagnosis_fails_validation(
    valid_claim,
    active_diagnosis_codes,
):
    claim = valid_claim.copy()
    claim["diagnosis_code"] = "DX999"

    errors = validate_claim(
        claim,
        active_diagnosis_codes,
    )

    assert any(
        "invalid or inactive" in error
        for error in errors
    )