from dataclasses import dataclass
from enum import StrEnum
from typing import Any


DEFAULT_MAX_RETRIES = 3


class RetryStatus(StrEnum):
    """
    Supported retry-queue statuses.
    """

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class RetryQueueItem:
    """
    One retry-queue record.
    """

    retry_id: int
    claim_id: str
    failed_step: str
    retry_count: int
    max_retries: int
    retry_status: RetryStatus
    last_error: str | None


def build_retry_queue_item(
    row: dict[str, Any],
) -> RetryQueueItem:
    """
    Convert a PostgreSQL row into a RetryQueueItem.
    """
    return RetryQueueItem(
        retry_id=int(
            row["retry_id"]
        ),
        claim_id=str(
            row["claim_id"]
        ),
        failed_step=str(
            row["failed_step"]
        ),
        retry_count=int(
            row["retry_count"]
        ),
        max_retries=int(
            row["max_retries"]
        ),
        retry_status=RetryStatus(
            row["retry_status"]
        ),
        last_error=(
            str(
                row["last_error"]
            )
            if row["last_error"] is not None
            else None
        ),
    )


def has_retry_attempts_remaining(
    retry_count: int,
    max_retries: int,
) -> bool:
    """
    Return whether another retry attempt is allowed.
    """
    return retry_count < max_retries


def get_overall_pricing_attempt(
    retry_count: int,
) -> int:
    """
    Convert the retry count into the overall pricing attempt number.

    Examples:

    retry_count = 1
        First retry
        Overall pricing attempt = 2

    retry_count = 2
        Second retry
        Overall pricing attempt = 3
    """
    if retry_count <= 0:
        raise ValueError(
            "retry_count must be greater than zero when "
            "calculating a retry pricing attempt."
        )

    return retry_count + 1