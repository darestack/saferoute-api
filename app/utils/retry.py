"""Retry logic utilities for SafeRoute API.

Provides reusable functions for:
- Determining if a delivery should be retried
- Calculating next retry timestamp with exponential backoff
- Getting retry window cutoff timestamps
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 5
DEFAULT_RETRY_WINDOW_DAYS = 7


def should_retry(status_code: int) -> bool:
    """Determine if a delivery should be retried based on status code.

    Retries only on reversible server errors: 502, 503, 504 and 429.

    Args:
        status_code: The HTTP status from the destination.

    Returns:
        ``True`` if the delivery should be retried.
    """
    return status_code in (429, 502, 503, 504)


def calculate_next_retry(
    retry_count: int,
    base_seconds: int = DEFAULT_BACKOFF_BASE_SECONDS,
    max_delay_seconds: int = 300,
) -> str:
    """Calculate the next retry timestamp with exponential backoff.

    Args:
        retry_count: The current retry attempt (0-based).
        base_seconds: Base delay for exponential backoff.
        max_delay_seconds: Maximum delay cap in seconds.

    Returns:
        ISO 8601 timestamp of the next retry.
    """
    delay = base_seconds * (2**retry_count)
    delay = min(delay, max_delay_seconds)
    return (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()


def get_retry_window_cutoff(
    days: int = DEFAULT_RETRY_WINDOW_DAYS,
) -> str:
    """Return the ISO timestamp for the oldest retryable log entry.

    Retries older than the specified days are no longer processed to prevent
    unbounded queue growth.

    Args:
        days: Number of days to look back.

    Returns:
        ISO 8601 timestamp for the cutoff.
    """
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
