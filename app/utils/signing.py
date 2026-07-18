"""Request/response signing utilities for proxy endpoints.

Adds HMAC-SHA256 signatures to proxy responses so clients can verify
that the response came from SafeRoute and wasn't tampered with.
"""

from __future__ import annotations
import hashlib
import hmac
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def sign_response(body: bytes, secret: str) -> str:
    """Sign a response body with HMAC-SHA256.

    Args:
        body: The response body bytes.
        secret: The shared secret for signing.

    Returns:
        Hex-encoded HMAC signature.
    """
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_response_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify a response signature.

    Args:
        body: The response body bytes.
        signature: The expected signature.
        secret: The shared secret.

    Returns:
        True if signature is valid, False otherwise.
    """
    expected = sign_response(body, secret)
    return hmac.compare_digest(expected, signature)


def get_signature_header(signature: str) -> str:
    """Format signature for HTTP header.

    Args:
        signature: The hex-encoded signature.

    Returns:
        Formatted header value.
    """
    return f"sha256={signature}"
