"""OAuth authentication endpoints.

Provides Google and GitHub OAuth flows via Supabase Auth. The frontend
should open the URL returned by ``/auth/oauth/{provider}`` in a browser
or popup. After the user authenticates, the OAuth provider redirects to
``/auth/callback`` with an authorization code, which this module exchanges
for a Supabase JWT session.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, ConfigDict

from app.config import settings
from app.database import supabase_client
from app.models import Token

router = APIRouter(prefix="/auth", tags=["OAuth Authentication"])


class OAuthRedirectResponse(BaseModel):
    """Response containing the URL to redirect the user to for OAuth."""

    auth_url: str


class CallbackResponse(BaseModel):
    """Response after successful OAuth callback."""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: Optional[str] = None


@router.get("/oauth/{provider}", response_model=OAuthRedirectResponse)
async def oauth_redirect(provider: str, request: Request):
    """Initiate an OAuth flow with the given provider.

    Supported providers: ``google``, ``github``.

    Args:
        provider: The OAuth provider name.
        request: The incoming request, used to build the redirect URI.

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

    redirect_uri = str(request.base_url).rstrip("/") + "/auth/callback"

    try:
        auth_url = supabase_client.auth.sign_in_with_oauth(
            {
                "provider": provider,
                "redirect_to": redirect_uri,
            }
        ).url

        return OAuthRedirectResponse(auth_url=auth_url)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initiate OAuth flow: {str(e)}",
        )


@router.get("/callback", response_model=CallbackResponse)
async def oauth_callback(code: str = Query(...), state: Optional[str] = Query(None)):
    """Handle the OAuth callback from Supabase.

    Supabase redirects here after the user authenticates with the provider.
    We exchange the authorization code for a session.

    Args:
        code: The authorization code from the OAuth provider.
        state: Optional state parameter for CSRF protection.

    Returns:
        Access token and user info on success.

    Raises:
        HTTPException: 400 if the code exchange fails.
    """
    try:
        result = supabase_client.auth.exchange_code_for_session(
            {"auth_code": code}
        )

        if result.session is None:
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
    except Exception as e:
        detail = str(e)
        if hasattr(e, "message") and e.message:
            detail = e.message
        raise HTTPException(
            status_code=400,
            detail=f"OAuth callback failed: {detail}",
        )
