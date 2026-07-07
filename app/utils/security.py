"""Security utilities for SafeRoute API.

Provides reusable security functions including:
- Webhook signature verification (HMAC-SHA256)
- Slug generation for route identifiers
- Safe error detail formatting
- Client IP extraction from requests
"""

import hashlib
import hmac
import ipaddress
import asyncio
import logging
import re
import secrets
import socket
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

if TYPE_CHECKING:
    from fastapi import Request

from app.config import settings

logger = logging.getLogger(__name__)

# Regex for slug sanitization: only lowercase alphanumeric and hyphens
_SLUG_PATTERN = re.compile(r"[^a-z0-9-]")
_DUPLICATE_HYPHEN_PATTERN = re.compile(r"-{2,}")

_ALLOWED_DESTINATION_SCHEMES = {"https"}


def _is_public_ip(address: str) -> bool:
    """Return True only for globally routable IP addresses."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    return ip.is_global


def validate_destination_url(url: str, resolve_dns: bool = True) -> None:
    """Validate that a webhook destination is safe to call.

    This is a no-cost SSRF guardrail. It rejects credentials in URLs and
    blocks localhost, private, loopback, link-local, multicast, reserved, and
    otherwise non-public IP destinations. When ``resolve_dns`` is enabled, DNS
    answers are checked as well; this reduces DNS-rebinding risk but cannot
    replace paid egress-firewall controls in hostile networks.

    Args:
        url: Destination URL supplied by a user.
        resolve_dns: Whether to resolve hostnames and validate returned IPs.

    Raises:
        ValueError: If the URL is not an allowed public HTTPS destination.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_DESTINATION_SCHEMES:
        raise ValueError("Destination URL must use HTTPS")

    if not parsed.hostname:
        raise ValueError("Destination URL must include a hostname")

    if parsed.username or parsed.password:
        raise ValueError("Destination URL must not include credentials")

    hostname = parsed.hostname.rstrip(".")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if not resolve_dns:
            return
    else:
        if not _is_public_ip(hostname):
            raise ValueError("Destination URL must resolve to a public IP")
        return

    if not resolve_dns:
        return

    try:
        addresses = socket.getaddrinfo(
            hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("Destination hostname could not be resolved") from exc

    if not addresses:
        raise ValueError("Destination hostname could not be resolved")

    for address in addresses:
        ip = str(address[4][0])
        if not _is_public_ip(ip):
            raise ValueError("Destination URL must resolve only to public IPs")


async def validate_destination_url_async(
    url: str,
    resolve_dns: bool = True,
) -> None:
    """Run destination URL validation without blocking the event loop."""
    await asyncio.to_thread(validate_destination_url, url, resolve_dns)


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
        trusted_proxies = [
            p.strip() for p in settings.TRUSTED_PROXIES.split(",") if p.strip()
        ]
        if trusted_proxies and client_host in trusted_proxies:
            return forwarded.split(",")[0].strip()
        if not trusted_proxies:
            return forwarded.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"
