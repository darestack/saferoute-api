"""Tests for the route L1+L2 cache (single-flight fill, eviction)."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio

from app.services import route_cache  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset the module-level cache between tests."""
    route_cache._route_cache._cache.clear()
    route_cache._route_cache_fills.clear()
    yield
    route_cache._route_cache._cache.clear()
    route_cache._route_cache_fills.clear()


class TestRouteCacheBasics:
    async def test_get_cached_route_passthrough(self):
        assert await route_cache.get_cached_route("missing") is None

    async def test_cache_route_stores_and_reads(self):
        await route_cache._cache_route("slug-1", {"id": "r1"})
        assert await route_cache.get_cached_route("slug-1") == {"id": "r1"}

    async def test_invalidate_removes_entry(self):
        await route_cache._cache_route("slug-1", {"id": "r1"})
        await route_cache.invalidate_route_cache("slug-1")
        assert await route_cache.get_cached_route("slug-1") is None

    async def test_clear_empty_is_safe(self):
        await route_cache.clear_route_cache()


class TestFillRouteCache:
    """fill_route_cache reads from Supabase; L2 cache is stubbed to isolate it."""

    @staticmethod
    def _l2_stack() -> ExitStack:
        """Enter the three L2 (Postgres) cache stubs in one ExitStack.

        The L2 cache is stubbed so DistributedCache never tries to serialize
        MagicMocks during these unit tests.
        """
        stack = ExitStack()
        stack.enter_context(
            patch("app.database.cache_get", new=AsyncMock(return_value=None))
        )
        stack.enter_context(patch("app.database.cache_set", new=AsyncMock()))
        stack.enter_context(patch("app.database.cache_delete", new=AsyncMock()))
        return stack

    async def test_fills_from_db_on_miss(self):
        fake_route = {"id": "r1", "slug": "slug-1", "is_active": True}
        mock_admin = MagicMock()
        # Mirror the real call chain used by fill_route_cache:
        #   admin.table("routes").select("*").eq("slug", slug).eq("is_active", True).execute()
        select = mock_admin.table.return_value.select.return_value
        eq_chain = select.eq.return_value
        eq_chain.eq.return_value = eq_chain
        eq_chain.execute.return_value.data = [fake_route]

        with self._l2_stack(), patch("app.services.route_cache.admin", mock_admin):
            route = await route_cache.fill_route_cache("slug-1")

        assert route == fake_route
        # Now served from L1 without another DB hit.
        mock_admin.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.reset_mock()
        with self._l2_stack(), patch("app.services.route_cache.admin", mock_admin):
            again = await route_cache.fill_route_cache("slug-1")
        assert again == fake_route
        mock_admin.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.assert_not_called()

    async def test_404_when_route_missing(self):
        mock_admin = MagicMock()
        select = mock_admin.table.return_value.select.return_value
        eq_chain = select.eq.return_value
        eq_chain.eq.return_value = eq_chain
        eq_chain.execute.return_value.data = []

        with self._l2_stack(), patch("app.services.route_cache.admin", mock_admin):
            with pytest.raises(HTTPException) as exc:
                await route_cache.fill_route_cache("nope")
            assert exc.value.status_code == 404

    async def test_single_flight_for_concurrent_misses(self):
        """Two concurrent fills for the same slug issue exactly one DB query."""
        fake_route = {"id": "r1", "slug": "slug-1", "is_active": True}
        call_count = {"n": 0}

        def _fake_execute():
            call_count["n"] += 1
            return MagicMock(data=[fake_route])

        mock_admin = MagicMock()
        select = mock_admin.table.return_value.select.return_value
        eq_chain = select.eq.return_value
        eq_chain.eq.return_value = eq_chain
        eq_chain.execute.side_effect = _fake_execute

        import asyncio

        with self._l2_stack(), patch("app.services.route_cache.admin", mock_admin):
            r1, r2 = await asyncio.gather(
                route_cache.fill_route_cache("slug-1"),
                route_cache.fill_route_cache("slug-1"),
            )
        assert r1 == fake_route and r2 == fake_route
        # Single-flight: the DB query must run only once.
        assert call_count["n"] == 1


class TestFillEviction:
    async def test_evicts_oldest_when_over_limit(self):
        # Lower the cap so eviction is exercised cheaply.
        original_max = route_cache._ROUTE_CACHE_FILLS_MAX_ENTRIES
        route_cache._ROUTE_CACHE_FILLS_MAX_ENTRIES = 4
        try:
            mock_admin = MagicMock()
            query = mock_admin.table.return_value.select.return_value
            query.eq.return_value = query

            def _route(i: int) -> dict:
                return {"id": f"r{i}", "slug": f"s{i}", "is_active": True}

            with patch("app.services.route_cache.admin", mock_admin):
                for i in range(6):
                    query.eq.return_value.limit.return_value.execute.return_value.data = [
                        _route(i)
                    ]
                    await route_cache.fill_route_cache(f"s{i}")
            # Fills map is bounded to the cap.
            assert len(route_cache._route_cache_fills) <= 4
        finally:
            route_cache._ROUTE_CACHE_FILLS_MAX_ENTRIES = original_max
