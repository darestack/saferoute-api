"""OAuth authentication endpoints.

Provides Google and GitHub OAuth flows via Supabase Auth. The frontend
should open the URL returned by ``/auth/oauth/{provider}`` in a browser
or popup. After the user authenticates, the OAuth provider redirects to
``/auth/callback`` with an authorization code, which this module exchanges
for a Supabase JWT session.
"""

import secrets
import hashlib
import base64
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict

from app.config import settings
from app.database import supabase_client, admin
from app.models import Token

router = APIRouter(prefix="/auth", tags=["OAuth Authentication"])


# ---------------------------------------------------------------------------
# PKCE storage
# ---------------------------------------------------------------------------
_PKCE_CODE_VERIFIER_LENGTH = 64


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code verifier and code challenge.

    Returns:
        A tuple of ``(code_verifier, code_challenge)``.
    """
    code_verifier = secrets.token_urlsafe(_PKCE_CODE_VERIFIER_LENGTH)
    hashed = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(hashed).rstrip(b"=").decode("utf-8")
    return code_verifier, code_challenge


def _store_pkce_verifier(code_challenge: str, code_verifier: str) -> None:
    """Store PKCE code verifier in Supabase for cross-worker accessibility.

    Args:
        code_challenge: The PKCE challenge to use as the key.
        code_verifier: The PKCE verifier to store.
    """
    admin.table("oauth_pkce").upsert(
        {
            "code_challenge": code_challenge,
            "code_verifier": code_verifier,
        }
    ).execute()


def _get_and_remove_pkce_verifier(code_challenge: str) -> Optional[str]:
    """Retrieve and delete PKCE code verifier from Supabase.

    Args:
        code_challenge: The PKCE challenge to look up.

    Returns:
        The code verifier string if found, else None.
    """
    result = (
        admin.table("oauth_pkce")
        .select("code_verifier")
        .eq("code_challenge", code_challenge)
        .execute()
    )

    if not result.data:
        return None

    verifier = result.data[0]["code_verifier"]
    admin.table("oauth_pkce").delete().eq("code_challenge", code_challenge).execute()
    return verifier


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

    Generates a PKCE pair, stores the verifier, and builds the authorize
    URL with explicit ``redirect_to`` so the user lands back on the
    correct frontend after auth.

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
            detail=f"Unsupported provider: {provider}. Use 'google' or 'github'.",
        )

    code_verifier, code_challenge = _generate_pkce_pair()
    _store_pkce_verifier(code_challenge, code_verifier)

    redirect_uri = settings.FRONTEND_URL.rstrip("/") + "/auth/callback"

    try:
        from urllib.parse import urlencode

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
    except Exception:
        _get_and_remove_pkce_verifier(code_challenge)
        raise HTTPException(
            status_code=500,
            detail="Failed to initiate OAuth flow",
        )


@router.get("/callback", response_model=CallbackResponse)
async def oauth_callback(
    code: str = Query(...),
    code_challenge: Optional[str] = Query(None),
):
    """Handle the OAuth callback from Supabase.

    Supabase redirects here after the user authenticates with the provider.
    We exchange the authorization code for a session using the stored
    PKCE ``code_verifier``.

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
            detail="Missing code_challenge parameter",
        )

    code_verifier = _get_and_remove_pkce_verifier(code_challenge)
    if not code_verifier:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired code_challenge",
        )

    try:
        result = supabase_client.auth.exchange_code_for_session(
            {
                "auth_code": code,
                "code_verifier": code_verifier,
            }
        )

        if result.session is None:
            raise HTTPException(
                status_code=400,
                detail="Failed to exchange authorization code for session",
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
        raise HTTPException(
            status_code=400,
            detail="OAuth callback failed",
        )