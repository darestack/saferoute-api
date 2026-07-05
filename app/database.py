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

    try:
        result = (
            admin.table("routes")
            .select("id")
            .eq("api_key_hash", key_hash)
            .execute()
        )

        if result.data:
            return result.data[0]["id"]  # type: ignore
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
