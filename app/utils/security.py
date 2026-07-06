"""Security utilities for SafeRoute API.

Provides reusable security functions including:
- Webhook signature verification (HMAC-SHA256)
- Slug generation for route identifiers
- Safe error detail formatting
- Client IP extraction from requests
"""

import hashlib
import hmac
import logging
import re
import secrets
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from fastapi import Request

from app.config import settings

logger = logging.getLogger(__name__)

# Regex for slug sanitization: only lowercase alphanumeric and hyphens
_SLUG_PATTERN = re.compile(r"[^a-z0-9-]")
_DUPLICATE_HYPHEN_PATTERN = re.compile(r"-{2,}")


def verify_webhook_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    secret: str,
) -> bool:
    """Verify an HMAC-SHA256 webhook signature.

    Supports the ``sha256=<hex>`` format used by GitHub, Stripe, and others.

    Args:
        raw_body: The raw request body bytes.
        signature_header: The signature header value (e.g., ``sha256=abc...``).
        secret: The shared secret for HMAC computation.

    Returns:
        ``True`` if the signature is valid or no verification is required.
    """
    if not signature_header and not secret:
        return True

    if not secret:
        return False

    if not signature_header:
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    # Support both "sha256=<hex>" and raw hex formats.
    provided = signature_header
    if provided.startswith("sha256="):
        provided = provided[7:]

    return hmac.compare_digest(expected, provided)


def generate_slug(name: str, user_id_suffix: str = "") -> str:
    """Generate a collision-safe slug from a route name.

    Args:
        name: The route name to convert to a slug.
        user_id_suffix: Optional suffix to include (typically user ID first chars).

    Returns:
        A URL-safe slug with random suffix to prevent collisions.
    """
    slug_base = _SLUG_PATTERN.sub("", name.lower().replace(" ", "-"))
    slug_base = _DUPLICATE_HYPHEN_PATTERN.sub("-", slug_base)
    slug_base = slug_base.strip("-")[:40] or "route"
    random_suffix = secrets.token_hex(3)
    return f"{slug_base}-{random_suffix}"


def safe_error_detail(exc: Exception) -> str:
    """Return a safe error detail — verbose in dev, generic in prod.

    Args:
        exc: The exception that occurred.

    Returns:
        The exception string in development, or a generic message in production.
    """
    if settings.ENVIRONMENT == "development":
        return str(exc)
    return "An internal error occurred"


def get_client_ip(request: "Request") -> str:
    """Extract the real client IP from the request.

    Prefers ``X-Forwarded-For`` when behind a CDN / Vercel edge, then falls
    back to the direct TCP peer address.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The client IP as a string, or ``"unknown"`` if unavailable.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_host = request.client.host if request.client else ""
        trusted_proxies = [p.strip() for p in settings.TRUSTED_PROXIES.split(",") if p.strip()]
        if trusted_proxies and client_host in trusted_proxies:
            return forwarded.split(",")[0].strip()
        if not trusted_proxies:
            return forwarded.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"