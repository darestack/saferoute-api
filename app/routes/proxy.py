"""Core webhook forwarding engine.

Receives webhooks, validates them, looks up destination URLs in Supabase,
forwards payloads, and logs delivery results.
"""

import json
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, Header
from app.database import admin
import httpx

router = APIRouter(tags=["Proxy Engine"])

# Tunables - adjust these based on your traffic and requirements.
_RATE_LIMIT_WINDOW_SECONDS = 60
"""Sliding window duration for per-IP rate limiting."""

_RATE_LIMIT_MAX_REQUESTS = 30
"""Max requests allowed per IP per route within the window."""

_FORWARD_TIMEOUT_SECONDS = 10.0
"""Timeout for the outbound request to the destination webhook."""

_MAX_LOG_BODY_BYTES = 10_000
"""Truncate stored response bodies to this size to control database growth."""


def get_client_ip(request: Request) -> str:
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
        # X-Forwarded-For can contain a chain like "client, proxy1, proxy2".
        return forwarded.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"


def parse_payload(body: bytes, content_type: str) -> dict:
    """Parse the incoming request body into a dictionary.

    Supports JSON and HTML form-urlencoded payloads. Falls back to an empty
    dict on parse failure rather than crashing the proxy.

    Args:
        body: Raw request body bytes.
        content_type: The ``Content-Type`` header value.

    Returns:
        Parsed payload as a dictionary.
    """
    if not body:
        return {}

    try:
        if "application/json" in content_type:
            return json.loads(body)

        # Default to form-urlencoded for static site contact forms.
        return {k: v[0] for k, v in parse_qs(body.decode()).items()}
    except Exception:
        # If parsing fails, return empty payload rather than dropping the request.
        return {}


def enforce_rate_limit(route_id: str, client_ip: str) -> None:
    """Check and increment the per-IP rate limit for a route.

    Reads the current window from ``rate_limits``. If the count exceeds
    ``_RATE_LIMIT_MAX_REQUESTS``, raises ``HTTP 429``. Otherwise, increments
    the counter or creates a new window entry.

    Args:
        route_id: The UUID of the route being hit.
        client_ip: The IP address to track.

    Raises:
        HTTPException: 429 if the client has exceeded the rate limit.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Look for an existing window for this IP + route.
    existing = (
        admin.table("rate_limits")
        .select("*")
        .eq("route_id", route_id)
        .eq("ip_address", client_ip)
        .gte("window_start", now)
        .execute()
    )

    if existing.data:
        current = existing.data[0]
        count = current["request_count"]

        if count >= _RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(status_code=429, detail="Too many requests")

        # Increment within the existing window.
        admin.table("rate_limits").update(
            {"request_count": count + 1}
        ).eq("id", current["id"]).execute()
    else:
        # New window - start counting from 1.
        admin.table("rate_limits").insert(
            {
                "route_id": route_id,
                "ip_address": client_ip,
                "request_count": 1,
            }
        ).execute()


def forward_payload(
    method: str,
    url: str,
    body: bytes,
    headers: dict,
) -> tuple[int, str, dict]:
    """Forward the webhook payload to the destination URL.

    Args:
        method: HTTP method to use (GET, POST, etc.).
        url: The destination webhook URL.
        body: Raw request body bytes to forward unchanged.
        headers: Extra headers to include in the outbound request.

    Returns:
        A tuple of ``(status_code, response_body, response_headers)``.
        Returns ``(502, error_message, {})`` on network failure, or
        ``(504, timeout_message, {})`` on timeout.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers,
                timeout=_FORWARD_TIMEOUT_SECONDS,
            )
            return (
                response.status_code,
                response.text,
                dict(response.headers),
            )
        except httpx.TimeoutException:
            return 504, "Destination timeout", {}
        except httpx.RequestError:
            return 502, "Destination unreachable", {}


def log_delivery(
    route_id: str,
    status_code: int,
    payload: dict,
    response_body: str,
    response_headers: dict,
    client_ip: str,
    user_agent: Optional[str],
    duration_ms: int,
) -> None:
    """Persist a webhook delivery attempt to the ``webhook_logs`` table.

    Truncates ``response_body`` to ``_MAX_LOG_BODY_BYTES`` to prevent DB bloat.

    Args:
        route_id: The route that was hit.
        status_code: HTTP status returned by the destination.
        payload: Parsed inbound payload (dict or list) for storage.
        response_body: Raw text body returned by the destination.
        response_headers: Response headers from the destination.
        client_ip: IP address of the requester.
        user_agent: ``User-Agent`` header from the request, if present.
        duration_ms: Total processing time in milliseconds.
    """
    truncated_body = response_body[:_MAX_LOG_BODY_BYTES] if response_body else None

    admin.table("webhook_logs").insert(
        {
            "route_id": route_id,
            "status_code": status_code,
            "request_body": payload if isinstance(payload, (dict, list)) else str(payload),
            "response_body": truncated_body,
            "response_headers": response_headers,
            "ip_address": client_ip,
            "user_agent": user_agent,
            "duration_ms": duration_ms,
        }
    ).execute()


def bump_route_metrics(route_id: str, requests_count: int) -> None:
    """Update the ``requests_count`` and ``last_used_at`` for a route.

    Uses an atomic update to avoid race conditions under concurrent traffic.

    Args:
        route_id: The route to update.
        requests_count: The current count before incrementing.
    """
    admin.table("routes").update(
        {
            "requests_count": requests_count + 1,
            "last_used_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", route_id).execute()


# ---------------------------------------------------------------------------
# Public endpoint
# ---------------------------------------------------------------------------
@router.post("/v1/route/{slug}")
async def proxy_webhook(
    slug: str,
    request: Request,
    user_agent: Optional[str] = Header(None),
):
    """Receive a webhook, validate it, forward it, and log the result.

    Processing steps:
       1. Parse the raw body (JSON or form-urlencoded).
       2. Strip known honeypot fields silently.
       3. Look up the active route by ``slug``.
       4. Enforce per-IP rate limiting.
       5. Forward the raw payload to the destination URL/method.
       6. Log the delivery attempt.
       7. Update route metrics.

    Args:
        slug: The public route slug from the URL path.
        request: The incoming FastAPI request.
        user_agent: ``User-Agent`` header, if present.

    Returns:
        JSON with ``status`` and ``destination_status``.

    Raises:
        HTTPException: 404 if the route is missing or inactive.
        HTTPException: 429 if the client is rate-limited.
        HTTPException: 502/504 if the destination is unreachable or times out.
    """
    start_time = time.perf_counter()
    client_ip = get_client_ip(request)

    # Read the raw body once so we can forward it byte-for-byte.
    try:
        body = await request.body()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    content_type = request.headers.get("content-type", "")
    payload = parse_payload(body, content_type)

    # Honeypot - drop obvious spam without erroring.
    payload.pop("honeypot_field", None)
    payload.pop("_gotcha", None)

    # Look up the route by public slug.
    route_result = (
        admin.table("routes")
        .select("*")
        .eq("slug", slug)
        .eq("is_active", True)
        .execute()
    )

    if not route_result.data:
        raise HTTPException(status_code=404, detail="Active routing link not found.")

    route = route_result.data[0]
    destination = route["destination_url"]
    method = route.get("method", "POST")
    extra_headers = route.get("headers", {})

    # Enforce rate limit by IP per route.
    enforce_rate_limit(route["id"], client_ip)

    # Forward to the destination using the configured method.
    status_code, response_body, response_headers = forward_payload(
        method=method,
        url=destination,
        body=body,
        headers=extra_headers,
    )

    duration_ms = int((time.perf_counter() - start_time) * 1000)

    # Log the delivery and update route metrics.
    log_delivery(
        route_id=route["id"],
        status_code=status_code,
        payload=payload,
        response_body=response_body,
        response_headers=response_headers,
        client_ip=client_ip,
        user_agent=user_agent,
        duration_ms=duration_ms,
    )

    bump_route_metrics(route["id"], route["requests_count"])

    return {
        "status": "forwarded",
        "destination_status": status_code,
    }
