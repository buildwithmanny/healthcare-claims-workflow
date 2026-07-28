import src.workflow_engine as workflow_engine

from src.state_manager import ClaimStatus


def test_one_failed_claim_does_not_stop_batch(
    monkeypatch,
    fraud_review_rules,
):
    claims = [
        {
            "claim_id": "GOOD001",
        },
        {
            "claim_id": "BAD001",
        },
        {
            "claim_id": "GOOD002",
        },
    ]

    processed_claim_ids: list[str] = []

    def fake_process_claim(
        claim,
        active_diagnosis_codes,
        member_index,
        pricing_rule_index,
        fraud_review_rules,
    ):
        claim_id = claim["claim_id"]

        processed_claim_ids.append(
            claim_id
        )

        if claim_id == "BAD001":
            raise RuntimeError(
                "Simulated unexpected database failure."
            )

        return workflow_engine.build_result(
            claim_id=claim_id,
            final_status=ClaimStatus.APPROVED,
        )

    def fake_persist_failure(
        claim,
        failure,
    ):
        return True

    monkeypatch.setattr(
        workflow_engine,
        "process_claim",
        fake_process_claim,
    )

    monkeypatch.setattr(
        workflow_engine,
        "persist_claim_processing_failure",
        fake_persist_failure,
    )

    results = workflow_engine.process_claim_batch(
        claims=claims,
        active_diagnosis_codes=set(),
        member_index={},
        pricing_rule_index={},
        fraud_review_rules=fraud_review_rules,
    )

    assert processed_claim_ids == [
        "GOOD001",
        "BAD001",
        "GOOD002",
    ]

    assert len(
        results
    ) == 3

    assert results[0].final_status == (
        ClaimStatus.APPROVED
    )

    assert results[1].final_status == (
        ClaimStatus.FAILED
    )

    assert results[1].processing_error is not None
    assert results[1].failure_persisted is True

    assert results[2].final_status == (
        ClaimStatus.APPROVED
    )