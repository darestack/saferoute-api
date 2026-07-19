"""PostgreSQL-backed shared circuit breaker.

Replaces the previous in-memory implementation so circuit breaker state is
shared across all workers/instances. Uses PostgreSQL advisory locks for
atomic state transitions.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import logging
import time

from app.config import settings
from app.database import admin, execute_query

logger = logging.getLogger(__name__)

_CIRCUIT_BREAKER_THRESHOLD = 5
_CIRCUIT_BREAKER_COOLDOWN_SECONDS = settings.CIRCUIT_BREAKER_TIMEOUT_SECONDS
_CIRCUIT_BREAKER_MAX_ENTRIES = 1_000

# Backward-compatible in-memory state (no longer primary source of truth;
# kept for tests that import these symbols directly).
_circuit_breaker_state: dict[str, dict] = {}


def _url_hash(url: str) -> int:
    """Compute a 32-bit advisory lock ID from a URL."""
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


async def is_circuit_breaker_open(url: str) -> bool:
    """Return True if the circuit breaker for this URL is open."""
    lock_id = _url_hash(url)
    try:
        async with await _acquire_advisory_lock(lock_id):
            result = await execute_query(
                admin.table("circuit_breaker_state")
                .select("state", "opened_at", "failure_count")
                .eq("destination_url", url)
                .limit(1)
            )

            if not result.data:
                return False

            row = result.data[0]
            state = row.get("state", "closed")
            opened_at = row.get("opened_at")

            if state != "open" or opened_at is None:
                return False

            now = time.time()
            opened_ts = calendar.timegm(time.strptime(opened_at[:19], "%Y-%m-%dT%H:%M:%S"))
            if now - opened_ts >= _CIRCUIT_BREAKER_COOLDOWN_SECONDS:
                await _transition_to_half_open(url)
                return False

            return True
    except Exception:
        logger.exception("Circuit breaker check failed for %s", url)
        return True


async def record_circuit_breaker_success(url: str) -> None:
    """Reset circuit breaker state after a successful request."""
    lock_id = _url_hash(url)
    try:
        async with await _acquire_advisory_lock(lock_id):
            await execute_query(
                admin.table("circuit_breaker_state")
                .delete()
                .eq("destination_url", url)
            )
    except Exception:
        logger.exception("Failed to record circuit breaker success for %s", url)


async def record_circuit_breaker_failure(url: str) -> None:
    """Record a failure and open the circuit if threshold is reached."""
    lock_id = _url_hash(url)
    try:
        async with await _acquire_advisory_lock(lock_id):
            result = await execute_query(
                admin.table("circuit_breaker_state")
                .select("failure_count", "state")
                .eq("destination_url", url)
                .limit(1)
            )

            current_count = 0
            current_state = "closed"
            if result.data:
                current_count = result.data[0].get("failure_count", 0)
                current_state = result.data[0].get("state", "closed")

            new_count = current_count + 1
            new_state = current_state
            opened_at = None

            if new_count >= _CIRCUIT_BREAKER_THRESHOLD:
                new_state = "open"
                opened_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            await execute_query(
                admin.table("circuit_breaker_state")
                .upsert(
                    {
                        "destination_url": url,
                        "state": new_state,
                        "failure_count": new_count,
                        "opened_at": opened_at,
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                    on_conflict="destination_url",
                )
            )
    except Exception:
        logger.exception("Failed to record circuit breaker failure for %s", url)


async def clear_route_circuit_breaker(url: str) -> None:
    """Clear circuit breaker state for a URL (e.g. after route update)."""
    lock_id = _url_hash(url)
    try:
        async with await _acquire_advisory_lock(lock_id):
            await execute_query(
                admin.table("circuit_breaker_state")
                .delete()
                .eq("destination_url", url)
            )
    except Exception:
        logger.exception("Failed to clear circuit breaker for %s", url)


async def get_circuit_breaker_stats() -> dict[str, dict]:
    """Return circuit breaker statistics for all tracked URLs."""
    try:
        result = await execute_query(
            admin.table("circuit_breaker_state")
            .select("destination_url", "state", "failure_count", "opened_at", "updated_at")
            .order("updated_at", desc=True)
        )

        stats = {}
        for row in result.data:
            stats[row["destination_url"]] = {
                "state": row.get("state", "closed"),
                "failure_count": row.get("failure_count", 0),
                "opened_at": row.get("opened_at"),
                "updated_at": row.get("updated_at"),
            }
        return stats
    except Exception:
        logger.exception("Failed to get circuit breaker stats")
        return {}


async def _acquire_advisory_lock(lock_id: int) -> asyncio.Lock:
    """Return a context manager that acquires a PostgreSQL advisory lock."""
    class AdvisoryLockContext:
        def __init__(self, lock_id: int) -> None:
            self._lock_id = lock_id

        async def __aenter__(self) -> None:
            await execute_query(
                admin.rpc("pg_advisory_xact_lock", {"lock_id": self._lock_id})
            )

        async def __aexit__(self, exc_type, exc, tb) -> None:
            pass

    return AdvisoryLockContext(lock_id)


async def _transition_to_half_open(url: str) -> None:
    """Transition a circuit breaker from open to half-open (probe allowed)."""
    try:
        await execute_query(
            admin.table("circuit_breaker_state")
            .update({"state": "closed", "failure_count": 0, "opened_at": None})
            .eq("destination_url", url)
        )
    except Exception:
        logger.exception("Failed to transition circuit breaker for %s", url)
