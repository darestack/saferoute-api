"""OAuth authentication endpoints.

Provides Google and GitHub OAuth flows via Supabase Auth. The frontend
should open the URL returned by ``/auth/oauth/{provider}`` in a browser
or popup. After the user authenticates, the OAuth provider redirects to
``/auth/callback`` with an authorization code, which this module exchanges
for a Supabase JWT session.
"""

from __future__ import annotations
import asyncio
import inspect
import logging
import time
from typing import Optional
from urllib.parse import urlencode, urljoin

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import settings
from app.database import admin, supabase_client
from app.utils.pkce import (
    generate_pkce_pair,
    store_pkce_verifier,
    retrieve_and_delete_pkce_verifier,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["OAuth Authentication"])

__all__ = [
    "router",
]

# ---------------------------------------------------------------------------
# OAuth callback rate limiting (per-IP, in-memory)
# ---------------------------------------------------------------------------
_OAUTH_CALLBACK_RATE_LIMIT = 10
_OAUTH_CALLBACK_RATE_WINDOW = 60
_OAUTH_CACHE_MAX_ENTRIES = 10_000

_oauth_callback_cache: dict[str, list[float]] = {}
_oauth_callback_lock = asyncio.Lock()


async def _check_oauth_rate_limit(client_ip: str) -> None:
    """Raise 429 if the client has exceeded the OAuth callback rate limit.

    The cache is bounded to ``_OAUTH_CACHE_MAX_ENTRIES`` entries to prevent
    memory leaks under sustained scanning. When the bound is exceeded, the
    oldest entries (by earliest timestamp) are evicted first.
    """
    async with _oauth_callback_lock:
        now = time.monotonic()
        window_start = now - _OAUTH_CALLBACK_RATE_WINDOW

        timestamps = _oauth_callback_cache.get(client_ip, [])
        timestamps = [ts for ts in timestamps if ts > window_start]

        if len(timestamps) >= _OAUTH_CALLBACK_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Too many OAuth callback attempts",
                headers={"Retry-After": str(_OAUTH_CALLBACK_RATE_WINDOW)},
            )

        timestamps.append(now)
        if timestamps:
            _oauth_callback_cache[client_ip] = timestamps
        else:
            _oauth_callback_cache.pop(client_ip, None)

        # Bounded eviction: drop the quarter with the oldest timestamps when
        # the cache exceeds ``_OAUTH_CACHE_MAX_ENTRIES``.
        if len(_oauth_callback_cache) > _OAUTH_CACHE_MAX_ENTRIES:
            sorted_ips = sorted(
                _oauth_callback_cache.items(),
                key=lambda kv: min(kv[1]) if kv[1] else 0,
            )
            evict_count = max(1, _OAUTH_CACHE_MAX_ENTRIES // 4)
            for ip, _ in sorted_ips[:evict_count]:
                _oauth_callback_cache.pop(ip, None)


# ---------------------------------------------------------------------------
# PKCE helpers (Supabase-backed for serverless safety)
# ---------------------------------------------------------------------------
def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code verifier and code challenge.

    Returns:
        A tuple of ``(code_verifier, code_challenge)``.
    """
    return generate_pkce_pair()


def _store_pkce_verifier(code_challenge: str, code_verifier: str) -> None:
    """Persist a PKCE verifier to the ``pkce_verifiers`` table."""
    store_pkce_verifier(admin, code_challenge, code_verifier)


def _retrieve_and_delete_pkce_verifier(code_challenge: str) -> Optional[str]:
    """Atomically retrieve and delete a PKCE verifier from the database.

    Uses the ``consume_pkce_verifier`` SQL function to prevent reuse races.

    Returns:
        The code verifier string, or ``None`` if not found.
    """
    return retrieve_and_delete_pkce_verifier(admin, code_challenge)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class OAuthRedirectResponse(BaseModel):
    """Response containing the URL to redirect the user to for OAuth."""

    auth_url: str


class CallbackResponse(BaseModel):
    """Response after successful OAuth callback."""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: Optional[str] = None


# ---------------------------------------------------------------------------
# OAuth endpoints
# ---------------------------------------------------------------------------
@router.get("/oauth/{provider}", response_model=OAuthRedirectResponse)
async def oauth_redirect(provider: str):
    """Initiate an OAuth flow with the given provider.

    Supported providers: ``google``, ``github``.

    Generates a PKCE pair, stores the verifier in the database, and builds
    the authorize URL with explicit ``redirect_to`` so the user lands back
    on the correct frontend after auth.

    Args:
        provider: The OAuth provider name.

    Returns:
        The Supabase-hosted OAuth URL to redirect the user to.

    Raises:
        HTTPException: 400 if the provider is not supported.
    """
    if provider not in ("google", "github"):
        raise HTTPException(
            status_code=400,
            detail=(f"Unsupported provider: {provider}. Use 'google' or 'github'."),
        )

    code_verifier, code_challenge = _generate_pkce_pair()

    try:
        _store_pkce_verifier(code_challenge, code_verifier)
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to initiate OAuth flow",
        )

    redirect_uri = urljoin(settings.FRONTEND_URL.rstrip("/") + "/", "auth/callback")

    params = {
        "provider": provider,
        "redirect_to": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{settings.SUPABASE_URL}/auth/v1/authorize?" + urlencode(params)

    return OAuthRedirectResponse(auth_url=auth_url)


@router.post("/callback", response_model=CallbackResponse)
async def oauth_callback_post(
    request: Request,
    code: str = Query(...),
    code_challenge: Optional[str] = Query(None),
):
    """Handle the OAuth callback from Supabase.

    The frontend must POST the authorization ``code`` here after Supabase
    redirects back. POST (not GET) is required so the code is not recorded in
    browser history or server access logs via the query string.

    Security notes:
        * The PKCE ``code_verifier`` is consumed (deleted) on first use by
          ``consume_pkce_verifier``, preventing replay of a captured code.
        * The frontend is responsible for binding this flow to the initiating
          session (e.g. via a same-site ``state`` cookie / session value). PKCE
          proves possession of the verifier but does not itself bind the flow to
          a specific browser session, so a frontend-side ``state`` check is the
          recommended defense against login-CSRF.

    Args:
        request: The incoming request (used for IP-based rate limiting).
        code: The authorization code from the OAuth provider.
        code_challenge: The PKCE challenge from the authorize request.

    Returns:
        Access token and user info on success.

    Raises:
        HTTPException: 400 if the code exchange fails or the challenge is
            missing/invalid.
        HTTPException: 429 if the client has exceeded the rate limit.
    """
    from app.utils.security import get_client_ip

    client_ip = get_client_ip(request)
    async with _oauth_callback_lock:
        await _check_oauth_rate_limit(client_ip)

    return await _exchange_code(code, code_challenge)


async def _exchange_code(code: str, code_challenge: Optional[str]) -> CallbackResponse:
    """Common code exchange logic for OAuth callback.

    Args:
        code: The authorization code from the OAuth provider.
        code_challenge: The PKCE challenge from the authorize request.

    Returns:
        Access token and user info on success.

    Raises:
        HTTPException: 400 if the code exchange fails or state is missing.
    """
    if not code_challenge:
        raise HTTPException(
            status_code=400,
            detail="Missing code_challenge parameter.",
        )

    code_verifier = _retrieve_and_delete_pkce_verifier(code_challenge)
    if not code_verifier:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired code_challenge.",
        )

    try:
        # supabase-py's CodeExchangeParams TypedDict marks ``redirect_to`` as
        # required, but the token endpoint accepts the call without it; the
        # ignore is scoped to that over-specified key only.
        result = supabase_client.auth.exchange_code_for_session(
            {  # type: ignore[typeddict-item]
                "auth_code": code,
                "code_verifier": code_verifier,
            }
        )
        if inspect.isawaitable(result):
            result = await result

        if result.session is None or result.user is None:
            raise HTTPException(
                status_code=400,
                detail="Failed to exchange authorization code for session.",
            )

        return CallbackResponse(
            access_token=result.session.access_token,
            token_type="bearer",
            user_id=result.user.id,
            email=result.user.email,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("OAuth callback failed")
        raise HTTPException(
            status_code=400,
            detail="OAuth callback failed",
        )
