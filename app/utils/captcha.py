"""CAPTCHA verification utilities.

Only Cloudflare Turnstile is wired into the proxy engine today. The
reCAPTCHA fallback path was removed as dead code to keep the attack
surface and dependency surface minimal.
"""

from __future__ import annotations
import logging

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
