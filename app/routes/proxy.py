"""Core webhook forwarding engine.

Receives webhooks, validates them, looks up destination URLs in Supabase,
forwards payloads, and logs delivery results. Supports:

* HMAC signature verification (per-route ``webhook_secret``)
* Per-route configurable rate limiting
* Idempotency keys to prevent duplicate deliveries
* Payload transformation via dot-notation templates
* DB-based retry queue for failed deliveries
"""

from __future__ import annotations
import ipaddress
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from typing import Any, Optional, cast

import asyncio
import math
import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.crypto import decrypt_webhook_secrets
from app.database import (
    admin,
    bump_route_metrics_atomic,
    deduct_user_credits,
    execute_query,
    get_http_client,
    verify_api_key,
)
from app.models import OutboundHealthResponse, RetryProcessResponse, CleanupResponse
from app.utils.retry import should_retry, calculate_next_retry
from app.utils.security import (
    verify_webhook_signature,
    get_client_ip,
    validate_destination_url_async,
)
from app.utils.transform import parse_payload, render_template
from app.utils.email import send_submission_email  # noqa: E402

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Proxy Engine"])

__all__ = [
    "router",
    "clear_route_cache",
    "clear_route_cache_for_route",
    "clear_circuit_breaker_for_url",
]

# ---------------------------------------------------------------------------
# IP geolocation cache (country code lookups)
# ---------------------------------------------------------------------------
from app.services.cache import DistributedCache  # noqa: E402

_ip_country_cache = DistributedCache(
    max_size=4096,
    default_ttl=3600,  # 1 hour TTL for geolocation results
)
"""Distributed cache for IP -> countryCode lookups."""

# NOTE: ip-api.com free tier only supports HTTP (not HTTPS). This means
# client IP addresses are sent over unencrypted HTTP for geolocation lookups.
# This is a privacy tradeoff accepted because the free tier has no rate limit
# and requires no API key. For higher privacy requirements, consider upgrading
# to ip-api.com pro tier or switching to a HTTPS-only geolocation provider.
_GEOLOCATION_URL = "http://ip-api.com/json/{ip}?fields=countryCode"
"""ip-api.com endpoint for country code lookups (free tier, no key)."""

_GEOLOCATION_TIMEOUT = settings.GEOLOCATION_TIMEOUT_SECONDS
"""Timeout for geolocation HTTP requests."""


async def _lookup_country_code(client_ip: str) -> Optional[str]:
    """Lookup the 2-letter country code for an IP address.

    Uses ip-api.com (free tier, ~45k requests/month, no API key).
    Results are cached in a distributed cache (L1 in-memory + L2 PostgreSQL).
    Failed lookups (including private/IPv6 addresses) are cached as ``None``
    to avoid repeated HTTP requests for the same IP.

    Args:
        client_ip: The IP address to look up.

    Returns:
        The 2-letter ISO country code, or ``None`` if lookup fails.
    """
    cached = await _ip_country_cache.get(client_ip)
    if cached is not None:
        return cast(Optional[str], cached)

    country_code: Optional[str] = None
    try:
        # Quick check: skip lookup for clearly non-public IPs to avoid
        # unnecessary HTTP requests to the geolocation service.
        try:
            ip = ipaddress.ip_address(client_ip)
            if not ip.is_global:
                # Private, loopback, link-local, etc. — cache as None.
                await _ip_country_cache.set(client_ip, None, ttl=3600)
                return None
        except ValueError:
            # Not a valid IP address (could be a hostname); proceed with lookup.
            pass

        client = get_http_client()
        response = await client.get(
            _GEOLOCATION_URL.format(ip=client_ip),
            timeout=_GEOLOCATION_TIMEOUT,
        )
        if response.status_code == 200:
            data = response.json()
            country_code = data.get("countryCode")
    except Exception:
        logger.debug("Geolocation lookup failed for IP %s", client_ip)

    await _ip_country_cache.set(client_ip, country_code, ttl=3600)
    return country_code


async def _verify_turnstile_token(
    token: str,
    secret_key: str,
    client_ip: str,
) -> bool:
    """Verify a Cloudflare Turnstile token.

    Args:
        token: The ``cf-turnstile-response`` token from the client.
        secret_key: The route's Turnstile secret key.
        client_ip: The client IP address for remoteip validation.

    Returns:
        ``True`` if the token is valid, ``False`` otherwise.
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

# Tunables — sourced from app.config.settings so they are runtime-overridable
# without code changes. The module-level names remain for backward compatibility
# with existing tests that patch them directly.
_RATE_LIMIT_WINDOW_SECONDS = settings.RATE_LIMIT_WINDOW_SECONDS
"""Sliding window duration for per-IP rate limiting."""

_DEFAULT_RATE_LIMIT = settings.DEFAULT_RATE_LIMIT
"""Default max requests per IP per route within the window."""

_FORWARD_TIMEOUT_SECONDS = settings.FORWARD_TIMEOUT_SECONDS
"""Timeout for the outbound request to the destination webhook."""

_MAX_LOG_BODY_BYTES = settings.MAX_LOG_BODY_BYTES
"""Truncate stored response bodies to this size to control database growth."""

_MAX_RETRIES = settings.MAX_RETRIES
"""Maximum number of retry attempts for failed deliveries."""

_RETRY_BATCH_SIZE = settings.RETRY_BATCH_SIZE
"""Maximum retry entries per /internal/process-retries call."""

# How long a row may stay claimed ("retrying") before the reaper considers the
# worker dead and returns it to the "pending" pool for another attempt.
_RETRY_CLAIM_STALE_SECONDS = settings.RETRY_CLAIM_STALE_SECONDS

from app.services.route_cache import (  # noqa: E402
    _cache_route,  # noqa: F401 - re-exported for tests
    get_cached_route as _get_cached_route,  # noqa: F401 - re-exported for tests
    _route_cache,  # noqa: F401 - re-exported for tests
    clear_route_cache,
    fill_route_cache,
    get_cached_route,
    invalidate_route_cache,
)


# ---------------------------------------------------------------------------
# Circuit breaker for outbound HTTP
# ---------------------------------------------------------------------------
from app.services.circuit_breaker import (  # noqa: E402
    _CIRCUIT_BREAKER_COOLDOWN_SECONDS,  # noqa: F401 - re-exported for tests
    _CIRCUIT_BREAKER_MAX_ENTRIES,  # noqa: F401 - re-exported for tests
    _CIRCUIT_BREAKER_THRESHOLD,  # noqa: F401 - re-exported for tests
    _circuit_breaker_state,  # noqa: F401 - re-exported for tests
    clear_route_circuit_breaker,
    is_circuit_breaker_open as _is_circuit_breaker_open,
    record_circuit_breaker_failure as _record_circuit_breaker_failure,
    record_circuit_breaker_success as _record_circuit_breaker_success,
)


async def clear_route_cache_for_route(slug: str) -> None:
    """Remove a route from the in-memory cache by slug."""
    await invalidate_route_cache(slug)


async def clear_circuit_breaker_for_url(url: str) -> None:
    """Reset circuit breaker state for a destination URL.

    Call this when a route's destination changes so a previously open circuit
    does not block traffic to the new endpoint.
    """
    await clear_route_circuit_breaker(url)


async def enforce_rate_limit(route_id: str, client_ip: str, max_requests: int) -> int:
    """Check and increment the per-IP rate limit for a route.

    Delegates to the atomic ``increment_rate_limit`` Postgres function, which
    buckets requests into fixed 60-second windows (see ``schema.sql`` /
    ``migration_005_rate_limiter_fix.sql``). The window boundary is computed
    server-side so counts accumulate correctly across requests.

    Args:
        route_id: The UUID of the route being hit.
        client_ip: The IP address to track.
        max_requests: Maximum allowed requests within the 60s window.

    Returns:
        Remaining allowed requests for this window.

    Raises:
        HTTPException: 429 if the client has exceeded the rate limit,
            with ``Retry-After`` header set to the window duration. The
            function fails *closed* (denies) if the RPC errors or returns no
            data, so an unavailable rate-limit store cannot be used to bypass
            the limit.
    """
    try:
        result = await execute_query(
            admin.rpc(
                "increment_rate_limit",
                {
                    "p_route_id": route_id,
                    "p_ip": client_ip,
                    "p_max_requests": max_requests,
                },
            )
        )

        if result.data:
            row = result.data[0]
            if not row.get("success"):
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests",
                    headers={"Retry-After": str(_RATE_LIMIT_WINDOW_SECONDS)},
                )
            new_count = cast(int, row.get("new_count", max_requests))
            return max(0, max_requests - new_count)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Rate limit check failed for route %s", route_id)

    raise HTTPException(
        status_code=429,
        detail="Too many requests",
        headers={"Retry-After": str(_RATE_LIMIT_WINDOW_SECONDS)},
    )


async def check_idempotency(route_id: str, idempotency_key: str) -> Optional[dict]:
    """Check if a request with this idempotency key was already processed.

    Args:
        route_id: The route UUID.
        idempotency_key: The idempotency key from the request header.

    Returns:
        The cached response dict if found and fresh (< 24h), or ``None``.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    result = await execute_query(
        admin.table("idempotency_cache")
        .select("*")
        .eq("route_id", route_id)
        .eq("idempotency_key", idempotency_key)
        .gte("created_at", cutoff)
    )

    if result.data:
        cached = cast(dict[str, Any], result.data[0])
        return cast(
            Optional[dict[str, Any]],
            {
                "status": "idempotent",
                "destination_status": cached["response_status"],
                "response_body": cached.get("response_body"),
                "response_headers": cached.get("response_headers") or {},
                "idempotent": True,
            },
        )

    return None


async def store_idempotency(
    route_id: str,
    idempotency_key: str,
    status_code: int,
    response_body: str,
    response_headers: dict,
) -> None:
    """Cache a delivery result for idempotency deduplication.

    Args:
        route_id: The route UUID.
        idempotency_key: The key from the request header.
        status_code: The HTTP status from the destination.
        response_body: The response body (truncated).
        response_headers: The response headers from the destination.
    """
    try:
        await execute_query(
            admin.table("idempotency_cache").upsert(
                {
                    "route_id": route_id,
                    "idempotency_key": idempotency_key,
                    "response_status": status_code,
                    "response_body": response_body[:_MAX_LOG_BODY_BYTES]
                    if response_body
                    else None,
                    "response_headers": response_headers,
                },
                on_conflict="route_id,idempotency_key",
            )
        )
    except Exception:
        logger.exception(
            "Failed to store idempotency cache entry for "
            "route_id=%s, idempotency_key=%s, status_code=%s",
            route_id,
            idempotency_key,
            status_code,
        )


async def claim_idempotency(route_id: str, idempotency_key: str) -> bool:
    """Atomically claim an idempotency key before forwarding.

    Uses the ``claim_idempotency_key`` Postgres function to insert a
    placeholder row with ``ON CONFLICT DO NOTHING``. Only one request
    per (route_id, idempotency_key) will succeed; others will get
    ``False`` and should wait for the cached result.

    Args:
        route_id: The route UUID.
        idempotency_key: The idempotency key to claim.

    Returns:
        ``True`` if the claim succeeded (caller is the leader),
        ``False`` if another request already claimed this key.
    """
    try:
        result = await execute_query(
            admin.rpc(
                "claim_idempotency_key",
                {
                    "p_route_id": route_id,
                    "p_idempotency_key": idempotency_key,
                },
            )
        )
        if result.data:
            return bool(result.data[0])
    except Exception:
        logger.exception("Failed to claim idempotency key")
    return False


async def _wait_for_idempotency_result(
    route_id: str,
    idempotency_key: str,
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> Optional[dict]:
    """Poll for an idempotency result until timeout.

    Used when another request has already claimed the same idempotency
    key. Returns the cached response once it's available, or ``None``
    on timeout.

    Args:
        route_id: The route UUID.
        idempotency_key: The idempotency key to wait for.
        timeout: Maximum seconds to wait.
        poll_interval: Seconds between polls.

    Returns:
        Cached response dict or ``None``.
    """
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        cached = await check_idempotency(route_id, idempotency_key)
        if cached:
            return cached
        await asyncio.sleep(poll_interval)
    return None


async def forward_payload(
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
    """
    if await _is_circuit_breaker_open(url):
        logger.warning("Circuit breaker open for %s", url)
        return 503, "Service unavailable (circuit breaker open)", {}

    client = get_http_client()
    try:
        response = await client.request(
            method=method,
            url=url,
            content=body,
            headers=headers,
            timeout=_FORWARD_TIMEOUT_SECONDS,
        )
        result = (
            response.status_code,
            response.text,
            {k: str(v) for k, v in response.headers.items()},
        )
        if 200 <= response.status_code < 300:
            await _record_circuit_breaker_success(url)
        else:
            await _record_circuit_breaker_failure(url)
        return result
    except httpx.TimeoutException:
        await _record_circuit_breaker_failure(url)
        return 504, "Destination timeout", {}
    except httpx.RequestError as exc:
        logger.warning("Destination unreachable: %s", exc)
        await _record_circuit_breaker_failure(url)
        return 502, "Destination unreachable", {}


async def log_delivery(
    route_id: str,
    status_code: int,
    payload: dict,
    response_body: str,
    response_headers: dict,
    client_ip: str,
    user_agent: Optional[str],
    duration_ms: int,
    content_type: str = "",
    idempotency_key: Optional[str] = None,
    retry_status: str = "none",
    next_retry_at: Optional[str] = None,
) -> Optional[int]:
    """Persist a webhook delivery attempt to the ``webhook_logs`` table.

    Args:
        route_id: The route that was hit.
        status_code: HTTP status returned by the destination.
        payload: Parsed inbound payload for storage.
        response_body: Raw text body returned by the destination.
        response_headers: Response headers from the destination.
        client_ip: IP address of the requester.
        user_agent: ``User-Agent`` header, if present.
        duration_ms: Total processing time in milliseconds.
        content_type: The ``Content-Type`` header of the inbound request.
        idempotency_key: Optional idempotency key for dedup.
        retry_status: Retry state for the log entry.
        next_retry_at: ISO 8601 timestamp of the next retry attempt.

    Returns:
        The log entry ID if insertion succeeded, or ``None``.
    """
    truncated_body = response_body[:_MAX_LOG_BODY_BYTES] if response_body else None

    # Populate error_message for non-2xx responses to aid diagnostics.
    error_message = None
    if status_code is not None and not (200 <= status_code < 300):
        error_message = response_body[:500] if response_body else f"HTTP {status_code}"

    try:
        result = await execute_query(
            admin.table("webhook_logs").insert(
                {
                    "route_id": route_id,
                    "status_code": status_code,
                    "request_body": (
                        payload if isinstance(payload, (dict, list)) else str(payload)
                    ),
                    "response_body": truncated_body,
                    "response_headers": response_headers,
                    "error_message": error_message,
                    "ip_address": client_ip,
                    "user_agent": user_agent,
                    "duration_ms": duration_ms,
                    "content_type": content_type,
                    "idempotency_key": idempotency_key,
                    "retry_status": retry_status,
                    "next_retry_at": next_retry_at,
                }
            )
        )

        if result.data:
            return cast(int, result.data[0].get("id"))
    except Exception:
        logger.exception("Failed to log delivery for route_id=%s", route_id)

    return None


# ---------------------------------------------------------------------------
# Public proxy endpoint
# ---------------------------------------------------------------------------


async def _authenticate_route(
    route: dict,
    x_api_key: Optional[str],
    body: bytes,
    x_hub_signature_256: Optional[str],
    x_webhook_signature: Optional[str],
) -> None:
    """Verify API key and webhook signature for the route.

    Raises:
        HTTPException: 401 if API key or signature verification fails.
    """
    if x_api_key:
        if await verify_api_key(x_api_key) is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

    raw_webhook_secrets = route.get("webhook_secrets") or route.get("webhook_secret")
    webhook_secrets: list[str] = []
    if raw_webhook_secrets:
        try:
            webhook_secrets = decrypt_webhook_secrets(raw_webhook_secrets)
        except ValueError as exc:
            raise HTTPException(
                status_code=500,
                detail="Webhook secret decryption failed",
            ) from exc

    if webhook_secrets:
        signature = x_hub_signature_256 or x_webhook_signature
        if not signature:
            raise HTTPException(
                status_code=401,
                detail="Missing webhook signature header",
            )
        for secret in webhook_secrets:
            if verify_webhook_signature(body, signature, secret):
                return
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature",
        )


def _apply_payload_transform(
    route: dict,
    payload: dict[str, Any],
    body: bytes,
    content_type: str,
) -> bytes:
    """Apply route-level payload transformation and return forward body.

    Reconstructs the forwarded body from the cleaned payload so that
    honeypot fields stripped earlier are never forwarded.
    """
    transform_template = route.get("transform_body_template")
    if transform_template:
        rendered = render_template(transform_template, payload)
        return rendered.encode("utf-8")

    if "application/json" in content_type or isinstance(payload, (dict, list)):
        try:
            return json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON payload",
            )

    if "application/x-www-form-urlencoded" in content_type:
        try:
            from urllib.parse import urlencode

            return urlencode(payload).encode("utf-8")
        except (TypeError, ValueError):
            return body

    return body


def _build_outbound_headers(route: dict, content_type: str) -> dict[str, str]:
    """Merge route headers with transform headers and preserve Content-Type."""
    outbound_headers = dict(route.get("headers", {}))
    transform_headers = route.get("transform_headers", {})
    if transform_headers:
        outbound_headers.update(transform_headers)

    if content_type and not any(
        key.lower() == "content-type" for key in outbound_headers
    ):
        outbound_headers["Content-Type"] = content_type

    return outbound_headers


def _validate_form_schema(payload: dict, form_schema: dict) -> None:
    """Validate payload fields against a form schema.

    Supported field constraints:
    - ``type``: ``string``, ``email``, ``number``
    - ``required``: boolean
    - ``max_length``: integer
    - ``min`` / ``max``: numeric bounds

    Args:
        payload: Parsed request body.
        form_schema: Route configuration from ``routes.form_schema``.

    Raises:
        HTTPException: 400 if validation fails.
    """
    if not form_schema or not isinstance(payload, dict):
        return

    fields = form_schema.get("fields", {})
    for field_name, rules in fields.items():
        if not isinstance(rules, dict):
            continue

        value = payload.get(field_name)
        required = rules.get("required", False)

        if required and (value is None or value == ""):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {field_name}",
            )

        if value is None or value == "":
            continue

        field_type = rules.get("type", "string")
        if field_type == "email":
            email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
            if not isinstance(value, str) or not email_re.match(value):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid email: {field_name}",
                )
            if rules.get("reject_disposable"):
                from app.utils.email import (
                    is_disposable_email,
                    _ensure_disposable_domains_loaded,
                )

                # Ensure the domain list is loaded before checking.
                _ensure_disposable_domains_loaded()

                if is_disposable_email(value):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Disposable email not allowed: {field_name}",
                    )
        elif field_type == "number":
            try:
                float(value)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid number: {field_name}",
                )
        elif field_type == "string":
            if not isinstance(value, str):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid string: {field_name}",
                )

        max_length = rules.get("max_length")
        if max_length is not None and len(str(value)) > max_length:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Field too long: {field_name}",
            )

        if field_type == "number" and isinstance(value, (int, float)):
            min_val = rules.get("min")
            max_val = rules.get("max")
            if min_val is not None and value < min_val:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Value too small: {field_name}",
                )
            if max_val is not None and value > max_val:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Value too large: {field_name}",
                )


async def _check_spam_shield(
    payload: dict,
    route: dict,
    client_ip: str,
    user_agent: Optional[str],
) -> None:
    """Apply spam checks: honeypot, User-Agent blocklist, country block.

    Args:
        payload: Parsed request body.
        route: Route configuration from database/cache.
        client_ip: Client IP address.
        user_agent: User-Agent header value.

    Raises:
        HTTPException: 400 if honeypot is triggered.
        HTTPException: 403 if User-Agent is blocked or country is not allowed.
    """
    honeypot_field = route.get("spam_honeypot_field")
    if honeypot_field and payload.get(honeypot_field):
        logger.info("Honeypot triggered for slug=%s", route.get("slug"))
        raise HTTPException(status_code=400, detail="Invalid submission")

    blocked_ua = route.get("spam_blocked_ua") or []
    if user_agent and isinstance(user_agent, str):
        ua_lower = user_agent.lower()
        for blocked in blocked_ua:
            if blocked.lower() in ua_lower:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )

    allowed_countries = route.get("spam_allowed_countries") or []
    if allowed_countries:
        country = await _lookup_country_code(client_ip)
        if country and country not in allowed_countries:
            logger.info(
                "Country blocked for slug=%s, country=%s, ip=%s",
                route.get("slug"),
                country,
                client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

    blocked_ips = route.get("spam_blocked_ips") or []
    if blocked_ips and client_ip in blocked_ips:
        logger.info(
            "IP blocked for slug=%s, ip=%s",
            route.get("slug"),
            client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    turnstile_enabled = route.get("turnstile_enabled")
    if turnstile_enabled:
        turnstile_token = payload.get("cf-turnstile-response")
        turnstile_secret = route.get("turnstile_secret_key")
        if not turnstile_token or not turnstile_secret:
            logger.info(
                "Turnstile missing token/secret for slug=%s",
                route.get("slug"),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Turnstile verification required",
            )

        valid = await _verify_turnstile_token(
            turnstile_token, turnstile_secret, client_ip
        )
        if not valid:
            logger.info(
                "Turnstile verification failed for slug=%s, ip=%s",
                route.get("slug"),
                client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Turnstile verification failed",
            )


@router.post("/v1/route/{slug}")
async def proxy_webhook(
    slug: str,
    request: Request,
    user_agent: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_hub_signature_256: Optional[str] = Header(None),
    x_webhook_signature: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Receive a webhook, validate it, forward it, and log the result.

    Processing steps:
       1. Parse the raw body (JSON or form-urlencoded).
       2. Strip known honeypot fields silently.
       3. Look up the active route by ``slug``.
       4. Verify webhook signature if route has a ``webhook_secret``.
       5. Check idempotency key if provided.
       6. Enforce per-IP rate limiting (uses route-level config).
       7. Apply payload transformation if configured.
       8. Forward the payload to the destination URL.
       9. Log the delivery attempt (with retry scheduling on failure).
       10. Update route metrics.

    Note:
        This is a transparent proxy: it always returns HTTP 200 to the caller
        and surfaces the destination status in the ``destination_status`` field
        of the response body. Clients should inspect that field rather than
        relying on the HTTP status code.

    Args:
        slug: The public route slug from the URL path.
        request: The incoming FastAPI request.
        user_agent: ``User-Agent`` header, if present.
        x_hub_signature_256: ``X-Hub-Signature-256`` for HMAC verification.
        x_webhook_signature: ``X-Webhook-Signature`` for HMAC verification.
        idempotency_key: ``Idempotency-Key`` to prevent duplicate deliveries.

    Returns:
        JSON with ``status`` and ``destination_status``.

    Raises:
        HTTPException: 401 if signature verification fails.
        HTTPException: 404 if the route is missing or inactive.
        HTTPException: 429 if the client is rate-limited.
    """
    start_time = time.perf_counter()
    client_ip = get_client_ip(request)

    try:
        body = await request.body()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    content_type = request.headers.get("content-type", "")
    payload = parse_payload(body, content_type)

    # Honeypot — drop obvious spam silently. Payloads are usually mappings,
    # but a webhook may legitimately send a JSON array or scalar; only strip
    # when the payload is a dict so non-object bodies are not 500'd.
    if isinstance(payload, dict):
        payload.pop("honeypot_field", None)
        payload.pop("_gotcha", None)

    # Look up the route by public slug.
    route = await get_cached_route(slug)
    if not route:
        route = await fill_route_cache(slug)

    _validate_form_schema(payload, route.get("form_schema") or {})
    await _check_spam_shield(payload, route, client_ip, user_agent)

    destination = route["destination_url"]
    try:
        # Cheap, DNS-free request-time guard. A full DNS-resolution SSRF check
        # (which also rejects DNS-rebound names) is performed at write time in
        # create_route/update_route, where the destination is server-controlled
        # and validated once. Re-resolving DNS on every forwarded webhook would
        # add latency on the hot path and reintroduce a TOCTOU window, so we
        # only re-check the scheme/credential/literal-IP invariants here.
        await validate_destination_url_async(destination, resolve_dns=False)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # --- Authentication ---
    await _authenticate_route(
        route, x_api_key, body, x_hub_signature_256, x_webhook_signature
    )

    # --- Rate limiting (per-route config) ---
    route_rate_limit = route.get("rate_limit", _DEFAULT_RATE_LIMIT)
    rate_limit_remaining = await enforce_rate_limit(
        route["id"], client_ip, route_rate_limit
    )

    # --- Idempotency check ---
    # Use atomic claim to prevent duplicate forwarding for concurrent
    # requests with the same idempotency key.
    if idempotency_key:
        cached = await check_idempotency(route["id"], idempotency_key)
        if cached:
            return JSONResponse(
                content={
                    "status": "idempotent",
                    "destination_status": cached["destination_status"],
                    "response_body": cached.get("response_body"),
                    "response_headers": cached.get("response_headers") or {},
                    "idempotent": True,
                },
                headers={"X-RateLimit-Remaining": str(rate_limit_remaining)},
            )

        claimed = await claim_idempotency(route["id"], idempotency_key)
        if not claimed:
            cached = await _wait_for_idempotency_result(route["id"], idempotency_key)
            if cached:
                return JSONResponse(
                    content={
                        "status": "idempotent",
                        "destination_status": cached["destination_status"],
                        "response_body": cached.get("response_body"),
                        "response_headers": cached.get("response_headers") or {},
                        "idempotent": True,
                    },
                    headers={"X-RateLimit-Remaining": str(rate_limit_remaining)},
                )

    # --- Payload transformation ---
    forward_body = _apply_payload_transform(route, payload, body, content_type)

    # --- Outbound headers ---
    outbound_headers = _build_outbound_headers(route, content_type)

    # --- Forward ---
    method = route.get("method", "POST")

    status_code, response_body, response_headers = await forward_payload(
        method=method,
        url=destination,
        body=forward_body,
        headers=outbound_headers,
    )

    duration_ms = int((time.perf_counter() - start_time) * 1000)

    logger.info(
        "Webhook delivered",
        extra={
            "route_id": route["id"],
            "status_code": status_code,
            "duration_ms": duration_ms,
        },
    )

    # --- Determine retry status ---
    retry_status = "none"
    next_retry_at = None
    if should_retry(status_code):
        retry_status = "pending"
        next_retry_at = calculate_next_retry(0)

    # --- Log delivery ---
    await log_delivery(
        route_id=route["id"],
        status_code=status_code,
        payload=payload,
        response_body=response_body,
        response_headers=response_headers,
        client_ip=client_ip,
        user_agent=user_agent,
        duration_ms=duration_ms,
        content_type=content_type,
        idempotency_key=idempotency_key,
        retry_status=retry_status,
        next_retry_at=next_retry_at,
    )

    # --- Credit deduction ---
    if status_code < 400:
        user_id = route.get("user_id")
        if user_id:
            await deduct_user_credits(user_id, 1)

    # --- Email notification ---
    email_config = route.get("email_notifications") or {}
    if (
        status_code < 400
        and email_config.get("enabled")
        and email_config.get("to")
    ):
        await send_submission_email(
            to=email_config["to"],
            subject=email_config.get("subject")
            or f"New submission: {route.get('name', route.get('slug', ''))}",
            payload=payload if isinstance(payload, dict) else {"raw": str(payload)},
            route_name=route.get("name") or route.get("slug", ""),
            reply_to=email_config.get("reply_to") or "",
        )

    # --- Store idempotency result ---
    if idempotency_key and status_code < 400:
        await store_idempotency(
            route["id"],
            idempotency_key,
            status_code,
            response_body,
            response_headers,
        )

    # --- Update route metrics ---
    await bump_route_metrics_atomic(route["id"])

    # Compute rate-limit metadata for response headers.
    # Align reset with the fixed 60s bucket boundary used by the
    # ``increment_rate_limit`` SQL function so clients can predict when
    # the window actually rolls over.
    rate_limit_reset = int(
        math.ceil(time.time() / _RATE_LIMIT_WINDOW_SECONDS) * _RATE_LIMIT_WINDOW_SECONDS
    )

    return JSONResponse(
        content={
            "status": "forwarded",
            "destination_status": status_code,
        },
        headers={
            "X-RateLimit-Remaining": str(rate_limit_remaining),
            "X-RateLimit-Limit": str(route_rate_limit),
            "X-RateLimit-Reset": str(rate_limit_reset),
        },
    )


from app.services.retry_processor import process_pending_retries  # noqa: E402


@router.post(
    "/internal/process-retries",
    response_model=RetryProcessResponse,
)
async def process_retries(
    request: Request,
    x_retry_secret: Optional[str] = Header(None, alias="X-Retry-Secret"),
):
    """Process pending webhook delivery retries."""
    if not settings.RETRY_ENDPOINT_SECRET or not compare_digest(
        x_retry_secret or "", settings.RETRY_ENDPOINT_SECRET
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    return await process_pending_retries(forward_payload)


from app.services.retention import run_cleanup  # noqa: E402


@router.post(
    "/internal/cleanup",
    response_model=CleanupResponse,
)
async def cleanup(
    request: Request,
    x_retry_secret: Optional[str] = Header(None, alias="X-Retry-Secret"),
    keep_days: int | None = None,
):
    """Run periodic retention cleanup to bound database growth."""
    if not settings.RETRY_ENDPOINT_SECRET or not compare_digest(
        x_retry_secret or "", settings.RETRY_ENDPOINT_SECRET
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    return await run_cleanup(keep_days)


@router.get(
    "/internal/health/outbound",
    response_model=OutboundHealthResponse,
)
async def outbound_health_check(
    x_retry_secret: Optional[str] = Header(None, alias="X-Retry-Secret"),
):
    """Check outbound HTTPS connectivity.

    Secured by the ``RETRY_ENDPOINT_SECRET`` shared secret to prevent
    unauthorized network probing. Sends a lightweight HEAD request to a
    well-known endpoint to verify that the application can reach the
    public internet. This detects network egress issues that would not
    be caught by the database health check alone.

    Args:
        x_retry_secret: The shared secret from ``RETRY_ENDPOINT_SECRET``.

    Returns:
        JSON with outbound connectivity status and latency.
    """
    if not settings.RETRY_ENDPOINT_SECRET or not compare_digest(
        x_retry_secret or "", settings.RETRY_ENDPOINT_SECRET
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    client = get_http_client()
    target = settings.OUTBOUND_HEALTH_CHECK_URL
    start = time.perf_counter()
    try:
        response = await client.head(target, timeout=_FORWARD_TIMEOUT_SECONDS)
        duration_ms = int((time.perf_counter() - start) * 1000)
        return OutboundHealthResponse(
            status="healthy",
            target=target,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.warning("Outbound health check failed: %s", exc)
        return OutboundHealthResponse(
            status="unhealthy",
            target=target,
            error=str(exc),
            duration_ms=duration_ms,
        )


@router.get(
    "/internal/cache/stats",
    summary="Cache statistics",
    description="Return detailed metrics for all distributed caches.",
)
async def cache_stats(request: Request) -> JSONResponse:
    """Return cache statistics for monitoring and debugging."""
    try:
        from app.routes.auth import _user_cache
        from app.services.route_cache import _route_cache
        from app.routes.proxy import _ip_country_cache
        from app.database import _api_key_cache

        caches = {
            "user_cache": _user_cache.get_metrics(),
            "route_cache": _route_cache.get_metrics(),
            "geolocation_cache": _ip_country_cache.get_metrics(),
            "api_key_cache": _api_key_cache.get_metrics(),
        }

        # Calculate aggregate stats
        total_hits = sum(c["hits"] for c in caches.values())
        total_misses = sum(c["misses"] for c in caches.values())
        total_l2_hits = sum(c["l2_hits"] for c in caches.values())
        total_l2_misses = sum(c["l2_misses"] for c in caches.values())
        total_size = sum(c["l1_size"] for c in caches.values())
        total_max = sum(c["l1_max_size"] for c in caches.values())

        return JSONResponse(
            status_code=200,
            content={
                "caches": caches,
                "aggregate": {
                    "total_hits": total_hits,
                    "total_misses": total_misses,
                    "total_l2_hits": total_l2_hits,
                    "total_l2_misses": total_l2_misses,
                    "overall_hit_rate": total_hits / (total_hits + total_misses) if (total_hits + total_misses) > 0 else 0.0,
                    "total_l1_size": total_size,
                    "total_l1_max_size": total_max,
                    "utilization_pct": round(total_size / total_max * 100, 1) if total_max > 0 else 0.0,
                },
            },
        )
    except Exception as exc:
        logger.error("Cache stats endpoint failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to retrieve cache stats"},
        )
