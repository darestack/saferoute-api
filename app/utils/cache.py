"""Generic TTL cache implementations with FIFO eviction.

Provides reusable cache components that can be used across the codebase
for caching routes, JWKS, users, and API keys.
"""

import asyncio
import threading
import time
from typing import Any, Optional


class TTLCache:
    """Thread-safe TTL cache with optional FIFO eviction.

    A generic cache that stores values with a time-to-live and optionally
    evicts oldest entries when the cache exceeds a maximum size.
    """

    def __init__(
        self,
        ttl_seconds: int,
        max_size: Optional[int] = None,
        use_lock: bool = True,
    ):
        """Initialize the TTL cache.

        Args:
            ttl_seconds: Time-to-live for cache entries in seconds.
            max_size: Maximum number of entries. Oldest entries are evicted
                when exceeded. If None, cache can grow unbounded.
            use_lock: If True, uses threading.Lock for sync operations.
                If False, assumes external synchronization.
        """
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._data: dict[Any, Any] = {}
        self._expiry: dict[Any, float] = {}
        self._order: list[Any] = []
        self._lock = threading.Lock() if use_lock else None

    def _with_lock(self, func):
        """Execute a function with lock protection if lock is enabled."""
        if self._lock:
            with self._lock:
                return func()
        return func()

    def get(self, key: Any) -> Optional[Any]:
        """Get a value from the cache if present and not expired.

        Args:
            key: The cache key to look up.

        Returns:
            The cached value or None if not found/expired.
        """
        def _get():
            now = time.monotonic()
            expiry = self._expiry.get(key, 0.0)
            if key in self._data and now < expiry:
                return self._data[key]
            # Clean up expired entry
            if key in self._data:
                self._data.pop(key, None)
                self._expiry.pop(key, None)
                if key in self._order:
                    self._order.remove(key)
            return None

        return self._with_lock(_get)

    def set(self, key: Any, value: Any) -> None:
        """Store a value in the cache with TTL.

        Args:
            key: The cache key.
            value: The value to cache.
        """
        def _set():
            self._data[key] = value
            self._expiry[key] = time.monotonic() + self._ttl_seconds
            if key not in self._order:
                self._order.append(key)

            # FIFO eviction if over max size
            while self._max_size and len(self._order) > self._max_size:
                oldest = self._order.pop(0)
                self._data.pop(oldest, None)
                self._expiry.pop(oldest, None)

        self._with_lock(_set)

    def clear(self) -> None:
        """Clear all cache entries."""
        def _clear():
            self._data.clear()
            self._expiry.clear()
            self._order.clear()

        self._with_lock(_clear)


class AsyncTTLCache:
    """Async-safe TTL cache with FIFO eviction.

    Uses asyncio.Lock for synchronization in async contexts.
    """

    def __init__(
        self,
        ttl_seconds: int,
        max_size: Optional[int] = None,
    ):
        """Initialize the async TTL cache.

        Args:
            ttl_seconds: Time-to-live for cache entries in seconds.
            max_size: Maximum number of entries. Oldest entries are evicted
                when exceeded. If None, cache can grow unbounded.
        """
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._data: dict[Any, Any] = {}
        self._expiry: dict[Any, float] = {}
        self._order: list[Any] = []
        self._lock = asyncio.Lock()

    async def get(self, key: Any) -> Optional[Any]:
        """Get a value from the cache if present and not expired.

        Args:
            key: The cache key to look up.

        Returns:
            The cached value or None if not found/expired.
        """
        async with self._lock:
            now = time.monotonic()
            expiry = self._expiry.get(key, 0.0)
            if key in self._data and now < expiry:
                return self._data[key]
            # Clean up expired entry
            if key in self._data:
                self._data.pop(key, None)
                self._expiry.pop(key, None)
                if key in self._order:
                    self._order.remove(key)
            return None

    async def set(self, key: Any, value: Any) -> None:
        """Store a value in the cache with TTL.

        Args:
            key: The cache key.
            value: The value to cache.
        """
        async with self._lock:
            self._data[key] = value
            self._expiry[key] = time.monotonic() + self._ttl_seconds
            if key not in self._order:
                self._order.append(key)

            # FIFO eviction if over max size
            while self._max_size and len(self._order) > self._max_size:
                oldest = self._order.pop(0)
                self._data.pop(oldest, None)
                self._expiry.pop(oldest, None)


class FIFOCache(TTLCache):
    """Alias for TTLCache for backward compatibility.

    Maintained as a separate class name for semantic clarity in some contexts.
    """

    pass