"""Supabase client factory and shared instances.

This module creates and exports two Supabase clients:

* ``supabase_client`` — uses the anon / public key. Subject to RLS.
* ``admin`` — uses the service-role key. Bypasses RLS. Use only on the
  server side for operations like proxy lookups and log insertion.
"""

from supabase import Client, create_client

from app.config import settings


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
        raise RuntimeError("Database configuration error")

    return create_client(url, key)


# Shared module-level clients. Import these elsewhere rather than calling
# ``get_supabase_client()`` repeatedly.
supabase_client: Client = get_supabase_client()
admin: Client = get_supabase_client(use_service_role=True)
