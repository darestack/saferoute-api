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
import secrets
import time
from typing import Optional
from urllib.parse import urlencode, urljoin

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import settings
from app.database import admin, supabase_client
from app.utils.audit import log_audit_event  # noqa: E402
from app.utils.pkce import (
    generate_pkce_pair,
    store_pkce_verifier,
    retrieve_and_delete_pkce_verifier,
    retrieve_and_delete_pkce_verifier_by_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["OAuth Authentication"])

__all__ = [
    "router",
]

# ---------------------------------------------------------------------------
# OAuth callback rate limiting (per-IP, in-memory)
# ---------------------------------------------------------------------------
_OAUTH_CALLBACK_RATE_LIMIT = settings.OAUTH_CALLBACK_RATE_LIMIT
_OAUTH_CALLBACK_RATE_WINDOW = settings.OAUTH_CALLBACK_RATE_WINDOW_SECONDS
_OAUTH_CACHE_MAX_ENTRIES = 10_000

from collections import OrderedDict  # noqa: E402

_oauth_callback_cache: OrderedDict[str, list[float]] = OrderedDict()
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
        # Bound per-IP list size to prevent memory leak under sustained scanning.
        if len(timestamps) > _OAUTH_CALLBACK_RATE_LIMIT * 2:
            timestamps = timestamps[-_OAUTH_CALLBACK_RATE_LIMIT:]
        _oauth_callback_cache[client_ip] = timestamps
        _oauth_callback_cache.move_to_end(client_ip)

        # Bounded eviction: drop oldest LRU entries if we exceed capacity.
        while len(_oauth_callback_cache) > _OAUTH_CACHE_MAX_ENTRIES:
            _oauth_callback_cache.popitem(last=False)


# ---------------------------------------------------------------------------
# PKCE helpers (Supabase-backed for serverless safety)
# ---------------------------------------------------------------------------
def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code verifier and code challenge.

    Returns:
        A tuple of ``(code_verifier, code_challenge)``.
    """
    return generate_pkce_pair()


async def _store_pkce_verifier(code_challenge: str, code_verifier: str, state: Optional[str] = None) -> None:
    """Persist a PKCE verifier to the ``pkce_verifiers`` table."""
    await store_pkce_verifier(admin, code_challenge, code_verifier, state)

    # State is now stateless (JWT), no caching needed.


async def _retrieve_and_delete_pkce_verifier(code_challenge: str) -> Optional[str]:
    """Atomically retrieve and delete a PKCE verifier from the database.

    Uses the ``consume_pkce_verifier`` SQL function to prevent reuse races.

    Returns:
        The code verifier string, or ``None`` if not found.
    """
    return await retrieve_and_delete_pkce_verifier(admin, code_challenge)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class OAuthRedirectResponse(BaseModel):
    """Response containing the URL to redirect the user to for OAuth."""

    auth_url: str
    state: str


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
async def oauth_redirect(provider: str, request: Request):
    """Initiate an OAuth flow with the given provider.

    Supported providers: ``google``, ``github``.

    Generates a PKCE pair, stores the verifier in the database, and builds
    the authorize URL with explicit ``redirect_to`` so the user lands back
    on the correct frontend after auth.

    Args:
        provider: The OAuth provider name.
        request: Incoming HTTP request to infer origin when needed.

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

    state = secrets.token_urlsafe(32)

    try:
        await _store_pkce_verifier(code_challenge, code_verifier, state)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initiate OAuth flow: {str(e)}",
        )

    base_url = settings.FRONTEND_URL.rstrip("/")
    # If FRONTEND_URL is not set or defaults to localhost in production, infer from request headers
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host and ("localhost" not in host and "127.0.0.1" not in host):
        proto = request.headers.get("x-forwarded-proto", "https")
        base_url = f"{proto}://{host}"

    redirect_uri = urljoin(base_url + "/", "auth/callback")

    params = {
        "provider": provider,
        "redirect_to": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    auth_url = f"{settings.SUPABASE_URL}/auth/v1/authorize?" + urlencode(params)

    return OAuthRedirectResponse(auth_url=auth_url, state=state)


@router.post("/callback", response_model=CallbackResponse)
async def oauth_callback_post(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    code_challenge: Optional[str] = Query(None),
):
    """Handle the OAuth callback from Supabase.

    The frontend POSTs ``code``/``state``/``code_challenge`` in a
    JSON body (see ``frontend/src/callback.ts``); this handler reads
    them from the body when present and falls back to query parameters,
    so both call styles work.

    The frontend must POST the authorization ``code`` here after Supabase
    redirects back. POST (not GET) is required so the code is not recorded in
    browser history or server access logs via the query string.

    Security notes:
        * The PKCE ``code_verifier`` is consumed (deleted) on first use by
          ``consume_pkce_verifier``, preventing replay of a captured code.
        * The ``state`` parameter is validated to prevent login CSRF. The state
          is generated in the authorize request and must be returned by the
          callback.

    Args:
        request: The incoming request (used for IP-based rate limiting).
        code: The authorization code from the OAuth provider.
        state: The OAuth state parameter for CSRF validation.
        code_challenge: The PKCE challenge from the authorize request.

    Returns:
        Access token and user info on success.

    Raises:
        HTTPException: 400 if the code exchange fails or state is invalid.
        HTTPException: 429 if the client has exceeded the rate limit.
    """
    from app.utils.security import get_client_ip

    # Prefer values posted as JSON (frontend contract); fall back to
    # query parameters so older/alternate clients still work.
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
            code = code or body.get("code")
            state = state or body.get("state")
            code_challenge = code_challenge or body.get("code_challenge")
        except Exception:
            pass

    client_ip = get_client_ip(request)
    await _check_oauth_rate_limit(client_ip)

    # Validate state parameter to prevent CSRF.
    if not state:
        await log_audit_event(
            action="oauth.auth_failed",
            resource_type="oauth",
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            metadata={"reason": "missing_state"},
        )
        raise HTTPException(
            status_code=400,
            detail="Missing state parameter",
        )

    if not code:
        await log_audit_event(
            action="oauth.auth_failed",
            resource_type="oauth",
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            metadata={"reason": "missing_code"},
        )
        raise HTTPException(
            status_code=400,
            detail="Missing authorization code",
        )

    # Look up PKCE verifier by state token
    code_verifier = await retrieve_and_delete_pkce_verifier_by_state(admin, state)
    if not code_verifier:
        await log_audit_event(
            action="oauth.auth_failed",
            resource_type="oauth",
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            metadata={"reason": "invalid_state"},
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired state parameter",
        )

    return await _exchange_code(code, code_verifier, client_ip)


async def _exchange_code(
    code: str, code_verifier: str, client_ip: Optional[str] = None
) -> CallbackResponse:
    """Common code exchange logic for OAuth callback.

    Args:
        code: The authorization code from the OAuth provider.
        code_verifier: The PKCE verifier looked up by state token.
        client_ip: Client IP address for audit logging.

    Returns:
        Access token and user info on success.

    Raises:
        HTTPException: 400 if the code exchange fails.
    """
    if not code_verifier:
        raise HTTPException(
            status_code=400,
            detail="Missing code_verifier.",
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
            await log_audit_event(
                action="oauth.auth_failed",
                resource_type="oauth",
                ip_address=client_ip,
                metadata={"reason": "exchange_failed"},
            )
            raise HTTPException(
                status_code=400,
                detail="Failed to exchange authorization code for session.",
            )

        await log_audit_event(
            action="oauth.auth_succeeded",
            resource_type="oauth",
            resource_id=result.user.id,
            ip_address=client_ip,
            metadata={"provider": "supabase"},
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
        await log_audit_event(
            action="oauth.auth_failed",
            resource_type="oauth",
            ip_address=client_ip,
            metadata={"reason": "unhandled_exception"},
        )
        raise HTTPException(
            status_code=400,
            detail="OAuth callback failed",
        )
