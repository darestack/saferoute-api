"""Supabase client factory and shared instances.

This module creates and exports two Supabase clients:

* ``supabase_client`` — uses the anon / public key. Subject to RLS.
* ``admin`` — uses the service-role key. Bypasses RLS. Use only on the
  server side for operations like proxy lookups and log insertion.
"""

from __future__ import annotations
import hmac
import logging
import secrets
import time
from typing import Any, Optional, cast

import asyncio
import httpx
from collections import OrderedDict
from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)

# Shared HTTP client for connection pooling across the application.
_http_client: Optional[httpx.AsyncClient] = None


async def execute_query(query: Any) -> Any:
    """Execute a Supabase query synchronously in a thread pool.

    ``supabase-py``'s ``.execute()`` is blocking. This helper wraps it in
    ``asyncio.to_thread`` so async route handlers do not stall the event loop.
    """
    return await asyncio.to_thread(query.execute)


def get_http_client() -> httpx.AsyncClient:
    """Return a shared async HTTP client with connection pooling.

    The client is created once and reused for all outbound requests,
    preventing connection exhaustion under load.
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=10.0,
                write=5.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
            ),
        )
    return _http_client


def has_http_client() -> bool:
    """Return whether the shared HTTP client has been created and is usable."""
    return _http_client is not None and not _http_client.is_closed


def _hash_api_key(full_key: str) -> str:
    """Compute the SHA-256 HMAC hash of an API key."""
    return hmac.new(
        settings.API_KEY_SALT.encode(),
        full_key.encode(),
        digestmod="sha256",
    ).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key for route authentication.

    Returns:
        A tuple of ``(full_key, prefix, hash)`` where:
        - ``full_key`` is the complete key shown to the user once.
        - ``prefix`` is the first 12 characters for display in the UI.
        - ``hash`` is the SHA-256 HMAC hash stored in the database.

    The key format is ``sk_live_<32 random hex chars>``.
    """
    random_hex = secrets.token_hex(16)
    full_key = f"sk_live_{random_hex}"
    prefix = full_key[:12]
    key_hash = _hash_api_key(full_key)

    return full_key, prefix, key_hash


async def verify_api_key(full_key: Optional[str]) -> Optional[str]:
    """Verify an API key and return the route ID if valid.

    Args:
        full_key: The complete API key from the request header.

    Returns:
        The route ID (UUID string) if the key is valid, or ``None`` if not.
    """
    if not full_key:
        return None

    key_hash = _hash_api_key(full_key)

    cached = await _get_cached_api_key(key_hash)
    if cached:
        return cached

    try:
        result = await execute_query(
            admin.table("routes").select("id").eq("api_key_hash", key_hash).limit(1)
        )

        if result.data:
            route_id = cast(str, result.data[0]["id"])
            await _cache_api_key(key_hash, route_id)
            return route_id
    except Exception:
        logger.exception(
            "Failed to verify API key (hash_prefix=%s)",
            key_hash[:16] if key_hash else "unknown",
        )

    return None


async def bump_route_metrics_atomic(route_id: str) -> None:
    """Atomically increment the request count for a route.

    Uses the ``increment_route_count`` SQL function defined in
    ``schema.sql`` to avoid read-then-write race conditions.

    Args:
        route_id: The UUID of the route to update.
    """
    try:
        await execute_query(
            admin.rpc("increment_route_count", {"p_route_id": route_id})
        )
    except Exception:
        logger.exception("Failed to increment route metrics for route_id=%s", route_id)


# Shared module-level clients. Import these elsewhere rather than calling
# ``get_supabase_client()`` repeatedly.
#
# Initialized at import time via get_supabase_client(), which creates the
# client on first call and caches it for subsequent calls. If environment
# variables are missing, the process fails fast during import rather than
# failing later during the first request.
_supabase_client: Optional[Client] = None
_admin_client: Optional[Client] = None


def get_supabase_client(use_service_role: bool = False) -> Client:
    """Return a cached Supabase client, creating it on first call."""
    global _supabase_client, _admin_client

    if use_service_role:
        if _admin_client is None:
            _admin_client = _create_supabase_client(use_service_role=True)
        return _admin_client

    if _supabase_client is None:
        _supabase_client = _create_supabase_client(use_service_role=False)
    return _supabase_client


def _create_supabase_client(use_service_role: bool = False) -> Client:
    """Create a new Supabase client instance."""
    url = settings.SUPABASE_URL
    key = (
        settings.SUPABASE_SERVICE_ROLE_KEY
        if use_service_role
        else settings.SUPABASE_KEY
    )

    if not url or not key:
        logger.error("Database configuration error: SUPABASE_URL or key is empty")
        raise RuntimeError("Database configuration error")

    return create_client(url, key)


# Convenience aliases for backward compatibility.
supabase_client = get_supabase_client(use_service_role=False)
admin = get_supabase_client(use_service_role=True)


# ---------------------------------------------------------------------------
# API key verification cache
# ---------------------------------------------------------------------------
_API_KEY_CACHE_TTL_SECONDS = 300
_API_KEY_CACHE_MAX_SIZE = 500
_api_key_cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
_api_key_route_index: dict[str, set[str]] = {}
_api_key_cache_lock = asyncio.Lock()


async def _get_cached_api_key(key_hash: str) -> Optional[str]:
    """Return a cached route_id for an API key hash if available and fresh."""
    async with _api_key_cache_lock:
        now = time.monotonic()
        if key_hash in _api_key_cache:
            route_id, expiry = _api_key_cache[key_hash]
            if now < expiry:
                _api_key_cache.move_to_end(key_hash)
                return route_id
            else:
                del _api_key_cache[key_hash]
                if route_id in _api_key_route_index:
                    _api_key_route_index[route_id].discard(key_hash)
                    if not _api_key_route_index[route_id]:
                        del _api_key_route_index[route_id]
        return None


async def _cache_api_key(key_hash: str, route_id: str) -> None:
    """Store an API key hash → route_id mapping with TTL and max size."""
    async with _api_key_cache_lock:
        if key_hash in _api_key_cache:
            _api_key_cache.move_to_end(key_hash)
        _api_key_cache[key_hash] = (
            route_id,
            time.monotonic() + _API_KEY_CACHE_TTL_SECONDS,
        )
        _api_key_route_index.setdefault(route_id, set()).add(key_hash)
        while len(_api_key_cache) > _API_KEY_CACHE_MAX_SIZE:
            evicted_hash, (evicted_route, _) = _api_key_cache.popitem(last=False)
            if evicted_route in _api_key_route_index:
                _api_key_route_index[evicted_route].discard(evicted_hash)
                if not _api_key_route_index[evicted_route]:
                    del _api_key_route_index[evicted_route]


async def clear_api_key_cache_for_route(route_id: str) -> None:
    """Remove cached API-key lookups for a route after key rotation."""
    async with _api_key_cache_lock:
        hashes = _api_key_route_index.pop(route_id, set())
        for key_hash in hashes:
            _api_key_cache.pop(key_hash, None)


async def clear_api_key_cache() -> None:
    """Clear the entire API key verification cache.

    Must be called from an async context because it acquires
    ``_api_key_cache_lock`` to stay consistent with concurrent readers.
    """
    async with _api_key_cache_lock:
        _api_key_cache.clear()
        _api_key_route_index.clear()


# ---------------------------------------------------------------------------
# Distributed cache (L2 - PostgreSQL)
# ---------------------------------------------------------------------------
async def cache_get(key: str) -> Any | None:
    """Get a value from the distributed PostgreSQL cache.

    Args:
        key: Cache key.

    Returns:
        Cached value, or ``None`` if not found or expired.
    """
    try:
        result = await execute_query(
            admin.rpc("cache_get", {"p_key": key})
        )
        if result.data and result.data[0] is not None:
            return result.data[0]
    except Exception:
        logger.exception("Distributed cache get failed for key=%s", key)
    return None


async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> None:
    """Set a value in the distributed PostgreSQL cache.

    Args:
        key: Cache key.
        value: Value to cache (must be JSON-serializable).
        ttl_seconds: Time-to-live in seconds. Defaults to 300 (5 minutes).
    """
    try:
        import json
        await execute_query(
            admin.rpc("cache_set", {
                "p_key": key,
                "p_value": json.dumps(value),
                "p_ttl_seconds": ttl_seconds,
            })
        )
    except Exception:
        logger.exception("Distributed cache set failed for key=%s", key)


async def cache_delete(key: str) -> None:
    """Delete a value from the distributed PostgreSQL cache.

    Args:
        key: Cache key to delete.
    """
    try:
        await execute_query(
            admin.rpc("cache_delete", {"p_key": key})
        )
    except Exception:
        logger.exception("Distributed cache delete failed for key=%s", key)


async def cache_cleanup() -> int:
    """Clean up expired entries from the distributed cache.

    Returns:
        Number of expired entries removed.
    """
    try:
        result = await execute_query(
            admin.rpc("cache_cleanup")
        )
        if result.data and result.data[0] is not None:
            return int(result.data[0])
    except Exception:
        logger.exception("Distributed cache cleanup failed")
    return 0
