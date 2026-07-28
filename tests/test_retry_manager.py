import pytest

from src.retry_manager import (
    get_overall_pricing_attempt,
    has_retry_attempts_remaining,
)


def test_retry_attempt_maps_to_next_pricing_attempt():
    assert get_overall_pricing_attempt(
        1
    ) == 2

    assert get_overall_pricing_attempt(
        3
    ) == 4


def test_retry_remains_available_before_maximum():
    assert has_retry_attempts_remaining(
        retry_count=2,
        max_retries=3,
    ) is True


def test_retry_exhaustion_occurs_at_maximum():
    assert has_retry_attempts_remaining(
        retry_count=3,
        max_retries=3,
    ) is False


def test_retry_count_must_be_positive():
    with pytest.raises(
        ValueError,
    ):
        get_overall_pricing_attempt(
            0
        )