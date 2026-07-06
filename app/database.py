"""Supabase client factory and shared instances.

This module creates and exports two Supabase clients:

* ``supabase_client`` — uses the anon / public key. Subject to RLS.
* ``admin`` — uses the service-role key. Bypasses RLS. Use only on the
  server side for operations like proxy lookups and log insertion.
"""

import hashlib
import hmac
import logging
import secrets
import threading
import time
from typing import Optional

from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)


def get_supabase_client(use_service_role: bool = False) -> Client:
    """Create a Supabase client configured for the current environment.

    Args:
        use_service_role: If ``True``, use the service-role key to bypass
            Row Level Security. Should only be used in trusted server-side
            code such as the proxy engine.

    Returns:
        A configured :class:`supabase.Client` instance.

    Raises:
        RuntimeError: If the required environment variables are missing or
            empty.
    """
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


def _hash_api_key(full_key: str) -> str:
    """Compute the SHA-256 HMAC hash of an API key."""
    return hmac.new(
        settings.API_KEY_SALT.encode(),
        full_key.encode(),
        hashlib.sha256,
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


def verify_api_key(full_key: Optional[str]) -> Optional[str]:
    """Verify an API key and return the route ID if valid.

    Args:
        full_key: The complete API key from the request header.

    Returns:
        The route ID (UUID string) if the key is valid, or ``None`` if not.
    """
    if not full_key:
        return None

    key_hash = _hash_api_key(full_key)

    cached = _get_cached_api_key(key_hash)
    if cached:
        return cached

    try:
        result = (
            admin.table("routes")
            .select("id")
            .eq("api_key_hash", key_hash)
            .limit(1)
            .execute()
        )

        if result.data:
            route_id = result.data[0]["id"]
            _cache_api_key(key_hash, route_id)
            return route_id
    except Exception:
        logger.exception("Failed to verify API key")

    return None


def bump_route_metrics_atomic(route_id: str) -> None:
    """Atomically increment the request count for a route.

    Uses the ``increment_route_count`` SQL function defined in
    ``schema.sql`` to avoid read-then-write race conditions.

    Args:
        route_id: The UUID of the route to update.
    """
    try:
        admin.rpc("increment_route_count", {"p_route_id": route_id}).execute()
    except Exception:
        logger.exception(
            "Failed to increment route metrics for route_id=%s", route_id
        )


# Shared module-level clients. Import these elsewhere rather than calling
# ``get_supabase_client()`` repeatedly.
supabase_client: Client = get_supabase_client()
admin: Client = get_supabase_client(use_service_role=True)


# ---------------------------------------------------------------------------
# API key verification cache
# ---------------------------------------------------------------------------
_API_KEY_CACHE_TTL_SECONDS = 300
_API_KEY_CACHE_MAX_SIZE = 500
_api_key_cache: dict[str, str] = {}
_api_key_cache_expiry: dict[str, float] = {}
_api_key_cache_order: list[str] = []
_api_key_cache_lock = threading.Lock()


def _get_cached_api_key(key_hash: str) -> Optional[str]:
    """Return a cached route_id for an API key hash if available and fresh."""
    now = time.monotonic()
    expiry = _api_key_cache_expiry.get(key_hash, 0.0)
    if key_hash in _api_key_cache and now < expiry:
        return _api_key_cache[key_hash]
    return None


def _cache_api_key(key_hash: str, route_id: str) -> None:
    """Store an API key hash → route_id mapping with TTL and max size."""
    _api_key_cache[key_hash] = route_id
    _api_key_cache_expiry[key_hash] = time.monotonic() + _API_KEY_CACHE_TTL_SECONDS
    with _api_key_cache_lock:
        _api_key_cache_order.append(key_hash)
        oldest = None
        while len(_api_key_cache_order) > _API_KEY_CACHE_MAX_SIZE:
            oldest = _api_key_cache_order.pop(0)
        if oldest is not None:
            _api_key_cache.pop(oldest, None)
            _api_key_cache_expiry.pop(oldest, None)
