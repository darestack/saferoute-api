"""CAPTCHA verification utilities.

Supports Cloudflare Turnstile as primary and Google reCAPTCHA as fallback.
"""

from __future__ import annotations
import logging
from typing import Optional


from app.config import settings
from app.database import get_http_client

logger = logging.getLogger(__name__)


async def verify_turnstile_token(token: str, secret_key: str, client_ip: str) -> bool:
    """Verify a Cloudflare Turnstile token.

    Args:
        token: The cf-turnstile-response token.
        secret_key: The route's Turnstile secret key.
        client_ip: Client IP for remoteip validation.

    Returns:
        True if valid, False otherwise.
    """
    if not token or not secret_key:
        return False

    try:
        client = get_http_client()
        response = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": secret_key,
                "response": token,
                "remoteip": client_ip,
            },
            timeout=5.0,
        )
        if response.status_code == 200:
            result = response.json()
            return bool(result.get("success"))
    except Exception:
        logger.exception("Turnstile verification failed for IP %s", client_ip)

    return False


async def verify_recaptcha_token(token: str, secret_key: str, client_ip: str) -> bool:
    """Verify a Google reCAPTCHA token.

    Args:
        token: The g-recaptcha-response token.
        secret_key: The reCAPTCHA secret key.
        client_ip: Client IP address.

    Returns:
        True if valid, False otherwise.
    """
    if not token or not secret_key:
        return False

    try:
        client = get_http_client()
        response = await client.post(
            settings.RECAPTCHA_VERIFY_URL,
            data={
                "secret": secret_key,
                "response": token,
                "remoteip": client_ip,
            },
            timeout=5.0,
        )
        if response.status_code == 200:
            result = response.json()
            return bool(result.get("success")) and result.get("score", 0) >= 0.5
    except Exception:
        logger.exception("reCAPTCHA verification failed for IP %s", client_ip)

    return False


async def verify_captcha(
    turnstile_token: Optional[str],
    turnstile_secret: Optional[str],
    recaptcha_token: Optional[str],
    recaptcha_secret: Optional[str],
    client_ip: str,
) -> bool:
    """Verify CAPTCHA with fallback from Turnstile to reCAPTCHA.

    Tries Turnstile first, then falls back to reCAPTCHA if configured.

    Args:
        turnstile_token: Turnstile response token.
        turnstile_secret: Turnstile secret key.
        recaptcha_token: reCAPTCHA response token.
        recaptcha_secret: reCAPTCHA secret key.
        client_ip: Client IP address.

    Returns:
        True if any CAPTCHA passes, False otherwise.
    """
    # Try Turnstile first
    if turnstile_token and turnstile_secret:
        if await verify_turnstile_token(turnstile_token, turnstile_secret, client_ip):
            return True

    # Fallback to reCAPTCHA
    if recaptcha_token and recaptcha_secret:
        if await verify_recaptcha_token(recaptcha_token, recaptcha_secret, client_ip):
            return True

    return False
