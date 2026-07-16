import asyncio
import time
from typing import Optional, Any, cast
from fastapi import HTTPException

from collections import OrderedDict
from app.database import admin, execute_query
from app.services.cache import DistributedCache

_ROUTE_CACHE_TTL_SECONDS = 30
_ROUTE_CACHE_MAX_SIZE = 500

_route_cache = DistributedCache(
    max_size=_ROUTE_CACHE_MAX_SIZE,
    default_ttl=_ROUTE_CACHE_TTL_SECONDS,
)

_ROUTE_CACHE_FILLS_MAX_ENTRIES = 1_000
_route_cache_fills: "OrderedDict[str, tuple[asyncio.Future, float]]" = OrderedDict()
_route_cache_fills_lock = asyncio.Lock()


async def get_cached_route(slug: str) -> Optional[dict]:
    """Return a cached active route dict if available and fresh."""
    return await _route_cache.get(slug)


async def _cache_route(slug: str, route: dict) -> None:
    """Store a route in the cache with TTL and FIFO eviction."""
    await _route_cache.set(slug, route, ttl=_ROUTE_CACHE_TTL_SECONDS)


async def fill_route_cache(slug: str) -> dict:
    """Fetch a route from the database and cache it.

    This is the single-flight cache filler. Only one coroutine per slug
    executes the DB query; others await the same Future.
    """
    async with _route_cache_fills_lock:
        existing = _route_cache_fills.get(slug)
        if existing is not None:
            return cast(dict[str, Any], await existing[0])

        fut = asyncio.get_running_loop().create_future()
        _route_cache_fills[slug] = (fut, time.monotonic())

        # Cleanup old entries to prevent memory leak.
        # Cancel any pending futures before eviction to prevent
        # "Exception was never retrieved" warnings in Python 3.12+.
        if len(_route_cache_fills) > _ROUTE_CACHE_FILLS_MAX_ENTRIES:
            evict_count = max(1, _ROUTE_CACHE_FILLS_MAX_ENTRIES // 4)
            for _ in range(evict_count):
                _evict_key, (fut, _ts) = _route_cache_fills.popitem(last=False)
                if not fut.done():
                    fut.cancel()

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
    await _route_cache.delete(slug)


async def clear_route_cache() -> None:
    await _route_cache.clear()
