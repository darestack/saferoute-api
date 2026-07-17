"""Tests for the distributed cache layer (L1 in-memory + L2 PostgreSQL)."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.services.cache import DistributedCache


class TestDistributedCache:
    """Unit tests for DistributedCache with mocked L2."""

    def test_set_and_get_basic(self) -> None:
        """set() should store a value and get() should retrieve it."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            await cache.set("key1", "value1")
            assert await cache.get("key1") == "value1"

        asyncio.run(run())

    def test_get_missing_returns_none(self) -> None:
        """get() should return None for missing keys."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            assert await cache.get("nonexistent") is None

        asyncio.run(run())

    def test_set_with_custom_ttl(self) -> None:
        """set() should accept a custom TTL."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            await cache.set("key1", "value1", ttl=1)
            assert await cache.get("key1") == "value1"
            # Wait for TTL to expire
            time.sleep(1.5)
            assert await cache.get("key1") is None

        asyncio.run(run())

    def test_delete_removes_key(self) -> None:
        """delete() should remove a key from both L1 and L2."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            await cache.set("key1", "value1")
            assert await cache.get("key1") == "value1"
            await cache.delete("key1")
            assert await cache.get("key1") is None

        asyncio.run(run())

    def test_fifo_eviction_when_full(self) -> None:
        """When L1 exceeds max_size, oldest entries should be evicted."""
        cache = DistributedCache(max_size=3, default_ttl=300)

        async def run() -> None:
            await cache.set("key1", "value1")
            await cache.set("key2", "value2")
            await cache.set("key3", "value3")
            assert len(cache) == 3

            # Adding a 4th entry should evict the oldest (key1)
            await cache.set("key4", "value4")
            assert len(cache) == 3
            assert "key1" not in cache
            assert "key4" in cache

        asyncio.run(run())

    def test_l2_fallback_on_l1_miss(self) -> None:
        """When L1 misses, get() should fall back to L2."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            # Pre-populate L2 directly (bypassing L1)
            with patch("app.database.cache_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = '"l2_value"'
                result = await cache.get("l2_key")
                assert result == "l2_value"
                mock_get.assert_called_once_with("l2_key")

        asyncio.run(run())

    def test_l2_hit_repopulates_l1(self) -> None:
        """When L2 hits, the value should be repopulated in L1."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            # First get: L1 miss, L2 hit
            with patch("app.database.cache_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = '"l2_value"'
                result = await cache.get("l2_key")
                assert result == "l2_value"

            # Second get: should hit L1 directly (no L2 call)
            with patch("app.database.cache_get", new_callable=AsyncMock) as mock_get:
                result = await cache.get("l2_key")
                assert result == "l2_value"
                mock_get.assert_not_called()

        asyncio.run(run())

    def test_l2_unavailable_returns_none(self) -> None:
        """When L2 is unavailable, get() should return None."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            with patch("app.database.cache_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = None
                result = await cache.get("missing_key")
                assert result is None

        asyncio.run(run())

    def test_clear_removes_all_entries(self) -> None:
        """clear() should remove all entries from L1."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            await cache.set("key1", "value1")
            await cache.set("key2", "value2")
            assert len(cache) == 2

            await cache.clear()
            assert len(cache) == 0
            assert await cache.get("key1") is None
            assert await cache.get("key2") is None

        asyncio.run(run())

    def test_cleanup_removes_expired_entries(self) -> None:
        """cleanup() should remove expired entries from L1."""
        cache = DistributedCache(max_size=10, default_ttl=1)

        async def run() -> None:
            await cache.set("key1", "value1", ttl=1)
            assert len(cache) == 1

            # Wait for TTL to expire
            time.sleep(1.5)

            # Mock L2 cleanup to avoid DB dependency
            with patch(
                "app.database.cache_cleanup", new_callable=AsyncMock
            ) as mock_cleanup:
                mock_cleanup.return_value = 0
                removed = await cache.cleanup()
                assert removed == 0

            assert len(cache) == 0

        asyncio.run(run())

    def test_l2_get_exception_returns_none(self) -> None:
        """When L2 get raises, get() should return None without crashing."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            with patch("app.database.cache_get", new_callable=AsyncMock) as mock_get:
                mock_get.side_effect = RuntimeError("L2 is down")
                result = await cache.get("missing_key")
                assert result is None

        asyncio.run(run())

    def test_l2_set_exception_does_not_crash(self) -> None:
        """When L2 set raises, set() should still store in L1."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            with patch("app.database.cache_set", new_callable=AsyncMock) as mock_set:
                mock_set.side_effect = RuntimeError("L2 is down")
                await cache.set("key1", "value1")
                assert await cache.get("key1") == "value1"
                mock_set.assert_called_once()

        asyncio.run(run())

    def test_l2_delete_exception_does_not_crash(self) -> None:
        """When L2 delete raises, delete() should still remove from L1."""
        cache = DistributedCache(max_size=10, default_ttl=300)

        async def run() -> None:
            await cache.set("key1", "value1")
            with patch(
                "app.database.cache_delete", new_callable=AsyncMock
            ) as mock_delete:
                mock_delete.side_effect = RuntimeError("L2 is down")
                await cache.delete("key1")
                assert await cache.get("key1") is None
                mock_delete.assert_called_once()

        asyncio.run(run())

    def test_l2_cleanup_exception_returns_zero(self) -> None:
        """When L2 cleanup raises, cleanup() should return 0 and keep L1 clean."""
        cache = DistributedCache(max_size=10, default_ttl=1)

        async def run() -> None:
            await cache.set("key1", "value1", ttl=1)
            assert len(cache) == 1

            time.sleep(1.5)

            with patch(
                "app.database.cache_cleanup", new_callable=AsyncMock
            ) as mock_cleanup:
                mock_cleanup.side_effect = RuntimeError("L2 is down")
                removed = await cache.cleanup()
                assert removed == 0

            assert len(cache) == 0

        asyncio.run(run())


class TestDatabaseCacheRPC:
    """Integration tests for cache RPC functions (requires database migration 013)."""

    @pytest.mark.skip(reason="Requires migration 013 applied to database")
    def test_cache_set_and_get(self) -> None:
        """cache_set and cache_get should round-trip a value."""

    @pytest.mark.skip(reason="Requires migration 013 applied to database")
    def test_cache_ttl_expiration(self) -> None:
        """cache_set with short TTL should expire."""
