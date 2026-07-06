"""OAuth authentication endpoints.

Provides Google and GitHub OAuth flows via Supabase Auth. The frontend
should open the URL returned by ``/auth/oauth/{provider}`` in a browser
or popup. After the user authenticates, the OAuth provider redirects to
``/auth/callback`` with an authorization code, which this module exchanges
for a Supabase JWT session.
"""

import hashlib
import logging
import secrets
import base64
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import settings
from app.database import admin, supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["OAuth Authentication"])


# ---------------------------------------------------------------------------
# PKCE helpers (Supabase-backed for serverless safety)
# ---------------------------------------------------------------------------
_PKCE_CODE_VERIFIER_LENGTH = 64


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code verifier and code challenge.

    Returns:
        A tuple of ``(code_verifier, code_challenge)``.
    """
    code_verifier = secrets.token_urlsafe(_PKCE_CODE_VERIFIER_LENGTH)
    hashed = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = (
        base64.urlsafe_b64encode(hashed).rstrip(b"=").decode("utf-8")
    )
    return code_verifier, code_challenge


def _store_pkce_verifier(code_challenge: str, code_verifier: str) -> None:
    """Persist a PKCE verifier to the ``pkce_verifiers`` table.

    This replaces the in-memory dict so the verifier survives across
    serverless invocations and multi-worker deployments.

    Args:
        code_challenge: The S256 challenge sent to the OAuth provider.
        code_verifier: The corresponding verifier to store.
    """
    try:
        admin.table("pkce_verifiers").insert(
            {
                "code_challenge": code_challenge,
                "code_verifier": code_verifier,
            }
        ).execute()
    except Exception:
        logger.exception("Failed to store PKCE verifier")
        raise


def _retrieve_and_delete_pkce_verifier(code_challenge: str) -> Optional[str]:
    """Atomically retrieve and delete a PKCE verifier from the database.

    Uses the ``consume_pkce_verifier`` SQL function to prevent reuse races.

    Args:
        code_challenge: The S256 challenge to look up.

    Returns:
        The code verifier string, or ``None`` if not found.
    """
    try:
        result = (
            admin.rpc("consume_pkce_verifier", {"p_code_challenge": code_challenge})
            .execute()
        )

        if result.data:
            return result.data[0]["code_verifier"]
    except Exception:
        logger.exception("Failed to retrieve PKCE verifier")

    return None


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
            detail=(
                f"Unsupported provider: {provider}. "
                "Use 'google' or 'github'."
            ),
        )

    code_verifier, code_challenge = _generate_pkce_pair()

    try:
        _store_pkce_verifier(code_challenge, code_verifier)
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to initiate OAuth flow",
        )

    redirect_uri = settings.FRONTEND_URL.rstrip("/") + "/auth/callback"

    params = {
        "provider": provider,
        "redirect_to": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = (
        f"{settings.SUPABASE_URL}/auth/v1/authorize?"
        + urlencode(params)
    )

    return OAuthRedirectResponse(auth_url=auth_url)


@router.post("/callback", response_model=CallbackResponse)
async def oauth_callback_post(
    code: str = Query(...),
    code_challenge: Optional[str] = Query(None),
):
    """Handle the OAuth callback from Supabase (POST preferred).

    The frontend should POST the authorization code here after Supabase
    redirects back to the frontend. This avoids putting the code in browser
    history or server logs via query parameters.

    Args:
        code: The authorization code from the OAuth provider.
        code_challenge: The PKCE challenge from the authorize request.

    Returns:
        Access token and user info on success.

    Raises:
        HTTPException: 400 if the code exchange fails or state is missing.
    """
    return await _exchange_code(code, code_challenge)


@router.get("/callback", response_model=CallbackResponse)
async def oauth_callback_get(
    code: str = Query(...),
    code_challenge: Optional[str] = Query(None),
):
    """Handle the OAuth callback from Supabase (GET fallback).

    .. deprecated::
        Use POST /auth/callback instead to avoid logging the authorization
        code in query strings.
    """
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
        result = supabase_client.auth.exchange_code_for_session(
            {  # type: ignore[arg-type, typeddict-item]
                "auth_code": code,
                "code_verifier": code_verifier,
            }
        )

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