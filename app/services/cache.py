"""L1 + L2 distributed cache for SafeRoute API.

Uses an in-memory OrderedDict as the fast L1 cache, with PostgreSQL as the
shared L2 fallback. This gives each worker process the speed of local memory
while still sharing data across workers via the database.

The cache is generic (type-safe via TypeVar) and supports:
- TTL-based expiration
- FIFO eviction when max size is reached
- Atomic get/set/delete operations
- Graceful degradation when L2 is unavailable
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from typing import Any, TypeVar

from app.database import cache_cleanup, cache_delete, cache_get, cache_set

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class DistributedCache:
    """Two-tier cache with in-memory L1 and PostgreSQL L2.

    Attributes:
        max_size: Maximum number of entries in the L1 cache.
        default_ttl: Default TTL in seconds for L2 entries.
    """

    def __init__(self, max_size: int = 1000, default_ttl: int = 300) -> None:
        """Initialize the distributed cache.

        Args:
            max_size: Maximum number of entries in the L1 cache.
            default_ttl: Default TTL in seconds for L2 entries.
        """
        self._cache: "OrderedDict[str, tuple[Any, float]]" = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_size = max_size
        self._default_ttl = default_ttl

    async def get(self, key: str) -> Any | None:
        """Get a value from the cache.

        Checks L1 first, then falls back to L2. On L2 hit, repopulates L1.

        Args:
            key: Cache key.

        Returns:
            Cached value, or ``None`` if not found or expired.
        """
        # L1 lookup (fast path)
        async with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.monotonic() < expiry:
                    self._cache.move_to_end(key)
                    return value
                else:
                    del self._cache[key]

        # L2 lookup (PostgreSQL)
        try:
            raw = await cache_get(key)
            if raw is not None:
                value = json.loads(raw) if isinstance(raw, str) else raw
                # Repopulate L1
                async with self._lock:
                    self._cache[key] = (value, time.monotonic() + self._default_ttl)
                    self._evict()
                return value
        except Exception:
            logger.exception("L2 cache get failed for key=%s", key)

        return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set a value in both L1 and L2.

        Args:
            key: Cache key.
            value: Value to cache (must be JSON-serializable).
            ttl: Time-to-live in seconds. Defaults to ``default_ttl``.
        """
        ttl = ttl or self._default_ttl

        # L1 store
        async with self._lock:
            self._cache[key] = (value, time.monotonic() + ttl)
            self._evict()

        # L2 store (fire-and-forget, don't block on DB errors)
        try:
            await cache_set(key, value, ttl)
        except Exception:
            logger.exception("L2 cache set failed for key=%s", key)

    async def delete(self, key: str) -> None:
        """Delete a value from both L1 and L2.

        Args:
            key: Cache key to delete.
        """
        # L1 delete
        async with self._lock:
            self._cache.pop(key, None)

        # L2 delete
        try:
            await cache_delete(key)
        except Exception:
            logger.exception("L2 cache delete failed for key=%s", key)

    async def clear(self) -> None:
        """Clear all entries from L1 and clean up expired L2 entries."""
        async with self._lock:
            self._cache.clear()

        # Clean up expired L2 entries
        try:
            removed = await cache_cleanup()
            logger.debug("Cleaned up %d expired cache entries from L2", removed)
        except Exception:
            logger.exception("L2 cache cleanup failed")

    async def cleanup(self) -> int:
        """Remove expired entries from L1 and L2.

        Returns:
            Number of expired L2 entries removed.
        """
        # L1 cleanup
        async with self._lock:
            now = time.monotonic()
            expired_keys = [
                key for key, (_, expiry) in self._cache.items() if now >= expiry
            ]
            for key in expired_keys:
                del self._cache[key]

        # L2 cleanup
        return await cache_cleanup()

    def _evict(self) -> None:
        """Evict oldest entries if L1 exceeds max size."""
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
