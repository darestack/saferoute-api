"""IP allowlist utilities for admin endpoints."""

from __future__ import annotations
import ipaddress
import logging

from fastapi import HTTPException, status
from starlette.requests import Request

from app.config import settings

logger = logging.getLogger(__name__)


def is_ip_allowed(client_ip: str, allowed_ips: str) -> bool:
    """Check if a client IP is in the allowed list.

    Supports individual IPs and CIDR notation.

    Args:
        client_ip: The client IP address.
        allowed_ips: Comma-separated list of allowed IPs/CIDRs.

    Returns:
        True if allowed, False otherwise.
    """
    if not allowed_ips.strip():
        return True

    allowed_list = [ip.strip() for ip in allowed_ips.split(",") if ip.strip()]

    for allowed in allowed_list:
        try:
            if "/" in allowed:
                network = ipaddress.ip_network(allowed, strict=False)
                if ipaddress.ip_address(client_ip) in network:
                    return True
            else:
                if client_ip == allowed:
                    return True
        except ValueError:
            logger.warning("Invalid IP/CIDR in allowlist: %s", allowed)

    return False


async def require_ip_allowlist(request: Request) -> None:
    """Dependency that enforces IP allowlist for admin endpoints.

    Raises:
        HTTPException: 403 if client IP is not allowed.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not is_ip_allowed(client_ip, settings.ADMIN_ALLOWED_IPS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: IP not allowed",
        )
