import asyncio
import time
from typing import Optional, Any, cast
from collections import OrderedDict
from fastapi import HTTPException

from app.database import admin, execute_query

_ROUTE_CACHE_TTL_SECONDS = 30
_ROUTE_CACHE_MAX_SIZE = 500

_route_cache: OrderedDict[str, tuple[dict, float]] = OrderedDict()
_route_cache_lock = asyncio.Lock()

_ROUTE_CACHE_FILLS_MAX_ENTRIES = 1_000
_route_cache_fills: OrderedDict[str, tuple[asyncio.Future, float]] = OrderedDict()
_route_cache_fills_lock = asyncio.Lock()


async def get_cached_route(slug: str) -> Optional[dict]:
    """Return a cached active route dict if available and fresh."""
    async with _route_cache_lock:
        now = time.monotonic()
        if slug in _route_cache:
            route, expiry = _route_cache[slug]
            if now < expiry:
                _route_cache.move_to_end(slug)
                return route
            else:
                del _route_cache[slug]
        return None


async def _cache_route(slug: str, route: dict) -> None:
    """Store a route in the cache with TTL and FIFO eviction."""
    async with _route_cache_lock:
        if slug in _route_cache:
            _route_cache.move_to_end(slug)
        _route_cache[slug] = (route, time.monotonic() + _ROUTE_CACHE_TTL_SECONDS)
        while len(_route_cache) > _ROUTE_CACHE_MAX_SIZE:
            _route_cache.popitem(last=False)


async def fill_route_cache(slug: str) -> dict:
    """Fetch a route from the database and cache it.

    This is the single-flight cache filler. Only one coroutine per slug
    executes the DB query; others await the same Future.
    """
    async with _route_cache_fills_lock:
        existing = _route_cache_fills.get(slug)
        if existing is not None:
            return await existing[0]

        fut = asyncio.get_running_loop().create_future()
        _route_cache_fills[slug] = (fut, time.monotonic())

        # Cleanup old entries to prevent memory leak
        if len(_route_cache_fills) > _ROUTE_CACHE_FILLS_MAX_ENTRIES:
            evict_count = max(1, _ROUTE_CACHE_FILLS_MAX_ENTRIES // 4)
            for _ in range(evict_count):
                _route_cache_fills.popitem(last=False)

    try:
        result = await execute_query(
            admin.table("routes").select("*").eq("slug", slug).eq("is_active", True)
        )

        if not result.data:
            raise HTTPException(
                status_code=404, detail="Active routing link not found."
            )

        route = cast(dict[str, Any], result.data[0])
        await _cache_route(slug, route)
        fut.set_result(route)
        return route
    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
            # Acknowledge the exception to avoid unretrieved exception warnings
            fut.exception()
        raise
    finally:
        async with _route_cache_fills_lock:
            _route_cache_fills.pop(slug, None)


async def invalidate_route_cache(slug: str) -> None:
    """Remove a route from the cache."""
    async with _route_cache_lock:
        _route_cache.pop(slug, None)


async def clear_route_cache() -> None:
    async with _route_cache_lock:
        _route_cache.clear()
