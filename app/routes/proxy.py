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
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from typing import Optional

import asyncio
import math
import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.crypto import decrypt_webhook_secret
from app.database import (
    admin,
    bump_route_metrics_atomic,
    get_http_client,
    verify_api_key,
)
from app.utils.retry import should_retry, calculate_next_retry, get_retry_window_cutoff
from app.utils.security import (
    verify_webhook_signature,
    get_client_ip,
    validate_destination_url_async,
)
from app.utils.transform import parse_payload, render_template

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Proxy Engine"])

__all__ = [
    "router",
    "clear_route_cache",
    "clear_route_cache_for_route",
    "clear_circuit_breaker_for_url",
]

# Tunables
_RATE_LIMIT_WINDOW_SECONDS = 60
"""Sliding window duration for per-IP rate limiting."""

_DEFAULT_RATE_LIMIT = 30
"""Default max requests per IP per route within the window."""

_FORWARD_TIMEOUT_SECONDS = 10.0
"""Timeout for the outbound request to the destination webhook."""

_MAX_LOG_BODY_BYTES = 10_000
"""Truncate stored response bodies to this size to control database growth."""

_MAX_RETRIES = 3
"""Maximum number of retry attempts for failed deliveries."""

# How long a row may stay claimed ("retrying") before the reaper considers the
# worker dead and returns it to the "pending" pool for another attempt.
_RETRY_CLAIM_STALE_SECONDS = 300

# In-memory route cache for performance.
_ROUTE_CACHE_TTL_SECONDS = 30
_ROUTE_CACHE_MAX_SIZE = 500

_route_cache: dict[str, dict] = {}
_route_cache_expiry: dict[str, float] = {}
_route_cache_order: list[str] = []
_route_cache_lock = asyncio.Lock()

# In-flight cache fills: prevents cache stampedes when many concurrent
# requests miss the cache for the same slug.
_route_cache_fills: dict[str, asyncio.Future] = {}
_route_cache_fills_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Circuit breaker for outbound HTTP
# ---------------------------------------------------------------------------
_CIRCUIT_BREAKER_THRESHOLD = 5
_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 60

_circuit_breaker_state: dict[str, dict] = {}
_circuit_breaker_lock = asyncio.Lock()


async def _is_circuit_breaker_open(url: str) -> bool:
    """Return True if the circuit breaker for this URL is open."""
    async with _circuit_breaker_lock:
        state = _circuit_breaker_state.get(url)
        if not state:
            return False

        if state.get("opened_at") is None:
            return False

        now = time.monotonic()
        if now - state["opened_at"] >= _CIRCUIT_BREAKER_COOLDOWN_SECONDS:
            # Cooldown expired; allow one probe request (half-open).
            state["opened_at"] = None
            state["failures"] = 0
            return False

        return True


async def _record_circuit_breaker_success(url: str) -> None:
    """Reset circuit breaker state after a successful request."""
    async with _circuit_breaker_lock:
        _circuit_breaker_state.pop(url, None)


async def _record_circuit_breaker_failure(url: str) -> None:
    """Record a failure and open the circuit if threshold is reached."""
    async with _circuit_breaker_lock:
        state = _circuit_breaker_state.setdefault(url, {"failures": 0, "opened_at": None})
        state["failures"] += 1
        if state["failures"] >= _CIRCUIT_BREAKER_THRESHOLD:
            state["opened_at"] = time.monotonic()


async def clear_route_circuit_breaker(url: str) -> None:
    """Clear circuit breaker state for a URL (e.g. after route update)."""
    async with _circuit_breaker_lock:
        _circuit_breaker_state.pop(url, None)


async def _get_cached_route(slug: str) -> Optional[dict]:
    """Return a cached active route dict if available and fresh."""
    async with _route_cache_lock:
        now = time.monotonic()
        expiry = _route_cache_expiry.get(slug, 0.0)
        if slug in _route_cache and now < expiry:
            return _route_cache[slug]
        return None


async def _cache_route(slug: str, route: dict) -> None:
    """Store a route in the cache with TTL and FIFO eviction."""
    async with _route_cache_lock:
        _route_cache[slug] = route
        _route_cache_expiry[slug] = time.monotonic() + _ROUTE_CACHE_TTL_SECONDS
        if slug not in _route_cache_order:
            _route_cache_order.append(slug)
        while len(_route_cache_order) > _ROUTE_CACHE_MAX_SIZE:
            oldest = _route_cache_order.pop(0)
            _route_cache.pop(oldest, None)
            _route_cache_expiry.pop(oldest, None)


async def _fill_route_cache(slug: str) -> dict:
    """Fetch a route from the database and cache it.

    This is the single-flight cache filler. Only one coroutine per slug
    executes the DB query; others await the same Future.
    """
    async with _route_cache_fills_lock:
        existing = _route_cache_fills.get(slug)
        if existing is not None:
            return await existing  # type: ignore[no-any-return]

        fut = asyncio.get_running_loop().create_future()
        _route_cache_fills[slug] = fut

    try:
        result = (
            admin.table("routes")
            .select("*")
            .eq("slug", slug)
            .eq("is_active", True)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404, detail="Active routing link not found."
            )

        route = result.data[0]
        await _cache_route(slug, route)
        fut.set_result(route)
        return route
    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        _route_cache_fills.pop(slug, None)


def clear_route_cache() -> None:
    """Clear the entire in-memory route cache.

    Primarily intended for test isolation; safe to call from synchronous
    test code without entering an async context.
    """
    _route_cache.clear()
    _route_cache_expiry.clear()
    _route_cache_order.clear()


def clear_route_cache_for_route(slug: str) -> None:
    """Evict a single route from the in-memory cache.

    Call this whenever a route's proxy-relevant columns change (destination,
    secret, method, headers, transforms, or ``is_active``) so the proxy stops
    serving a stale cached copy. Without this, such changes would take up to
    ``_ROUTE_CACHE_TTL_SECONDS`` (30s) to take effect — a security-relevant
    window for ``is_active`` toggles and secret rotations.
    """
    _route_cache.pop(slug, None)
    _route_cache_expiry.pop(slug, None)
    if slug in _route_cache_order:
        _route_cache_order.remove(slug)


async def clear_circuit_breaker_for_url(url: str) -> None:
    """Reset circuit breaker state for a destination URL.

    Call this when a route's destination changes so a previously open circuit
    does not block traffic to the new endpoint.
    """
    await clear_route_circuit_breaker(url)


def enforce_rate_limit(route_id: str, client_ip: str, max_requests: int) -> int:
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
        result = admin.rpc(
            "increment_rate_limit",
            {
                "p_route_id": route_id,
                "p_ip": client_ip,
                "p_max_requests": max_requests,
            },
        ).execute()

        if result.data:
            row = result.data[0]
            if not row.get("success"):
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests",
                    headers={"Retry-After": str(_RATE_LIMIT_WINDOW_SECONDS)},
                )
            new_count = row.get("new_count")
            if new_count is None:
                new_count = max_requests
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


def check_idempotency(route_id: str, idempotency_key: str) -> Optional[dict]:
    """Check if a request with this idempotency key was already processed.

    Args:
        route_id: The route UUID.
        idempotency_key: The idempotency key from the request header.

    Returns:
        The cached response dict if found and fresh (< 24h), or ``None``.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    result = (
        admin.table("idempotency_cache")
        .select("*")
        .eq("route_id", route_id)
        .eq("idempotency_key", idempotency_key)
        .gte("created_at", cutoff)
        .execute()
    )

    if result.data:
        cached = result.data[0]
        return {
            "status": "idempotent",
            "destination_status": cached["response_status"],
            "response_body": cached.get("response_body"),
            "response_headers": cached.get("response_headers") or {},
            "idempotent": True,
        }

    return None


def store_idempotency(
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
        ).execute()
    except Exception:
        logger.exception(
            "Failed to store idempotency cache entry for route_id=%s, idempotency_key=%s, status_code=%s",
            route_id,
            idempotency_key,
            status_code,
        )


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
            dict(response.headers),
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


def log_delivery(
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
        result = (
            admin.table("webhook_logs")
            .insert(
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
            .execute()
        )

        if result.data:
            return result.data[0].get("id")
    except Exception:
        logger.exception("Failed to log delivery for route_id=%s", route_id)

    return None


# ---------------------------------------------------------------------------
# Public proxy endpoint
# ---------------------------------------------------------------------------
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
    route = await _get_cached_route(slug)
    if not route:
        route = await _fill_route_cache(slug)

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

    # --- API key authentication (optional, defense-in-depth) ---
    # The random slug is the primary secret protecting a route's proxy URL. If
    # the caller also presents an ``X-API-Key``, it must be valid for *this*
    # route; an invalid key is rejected. A missing key is allowed (slug-only
    # auth), preserving compatibility with webhook senders that only know the
    # slug.
    if x_api_key:
        if await verify_api_key(x_api_key) is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

    # --- Signature verification ---
    raw_webhook_secret = route.get("webhook_secret")
    webhook_secret = None
    if raw_webhook_secret:
        try:
            webhook_secret = decrypt_webhook_secret(raw_webhook_secret)
        except ValueError as exc:
            raise HTTPException(
                status_code=500,
                detail="Webhook secret decryption failed",
            ) from exc

    if webhook_secret:
        signature = x_hub_signature_256 or x_webhook_signature
        if not signature:
            raise HTTPException(
                status_code=401,
                detail="Missing webhook signature header",
            )
        if not verify_webhook_signature(body, signature, webhook_secret):
            raise HTTPException(
                status_code=401,
                detail="Invalid webhook signature",
            )

    # --- Rate limiting (per-route config) ---
    route_rate_limit = route.get("rate_limit", _DEFAULT_RATE_LIMIT)
    rate_limit_remaining = enforce_rate_limit(route["id"], client_ip, route_rate_limit)

    # --- Idempotency check ---
    # NOTE: the cache is written *after* a successful forward (see
    # store_idempotency below), so two identical-key requests arriving truly
    # concurrently can both miss the cache and both forward. This is an
    # at-least-once best-effort guarantee suitable for webhooks whose
    # downstreams are idempotent; achieving exactly-once would require claiming
    # a placeholder before forwarding. The cache still fully de-duplicates
    # retries and any request that arrives after the first response is stored.
    if idempotency_key:
        cached = check_idempotency(route["id"], idempotency_key)
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
    # Always reconstruct the forwarded body from the cleaned `payload` so that
    # honeypot fields stripped above are never forwarded. Only fall back to
    # the raw bytes for content types we cannot safely re-encode (binary, etc.).
    transform_template = route.get("transform_body_template")
    if transform_template:
        rendered = render_template(transform_template, payload)
        forward_body = rendered.encode("utf-8")
    elif "application/json" in content_type or isinstance(payload, (dict, list)):
        try:
            forward_body = json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError):
            # Cannot safely re-serialize the cleaned payload; rejecting
            # rather than falling back to the raw body prevents honeypot
            # fields from leaking through to the destination.
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON payload",
            )
    elif "application/x-www-form-urlencoded" in content_type:
        try:
            from urllib.parse import urlencode

            forward_body = urlencode(payload).encode("utf-8")
        except (TypeError, ValueError):
            forward_body = body
    else:
        forward_body = body

    # Merge route-level transform headers with configured headers.
    outbound_headers = dict(route.get("headers", {}))
    transform_headers = route.get("transform_headers", {})
    if transform_headers:
        outbound_headers.update(transform_headers)

    # Preserve the inbound Content-Type unless the route explicitly overrides it.
    if content_type and not any(
        key.lower() == "content-type" for key in outbound_headers
    ):
        outbound_headers["Content-Type"] = content_type

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
    log_delivery(
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

    # --- Store idempotency result ---
    if idempotency_key and status_code < 400:
        store_idempotency(
            route["id"],
            idempotency_key,
            status_code,
            response_body,
            response_headers,
        )

    # --- Update route metrics ---
    bump_route_metrics_atomic(route["id"])

    # Compute rate-limit metadata for response headers.
    # Align reset with the fixed 60s bucket boundary used by the
    # ``increment_rate_limit`` SQL function so clients can predict when
    # the window actually rolls over.
    rate_limit_reset = int(math.ceil(time.time() / _RATE_LIMIT_WINDOW_SECONDS) * _RATE_LIMIT_WINDOW_SECONDS)

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


@router.post("/internal/process-retries")
async def process_retries(
    request: Request,
    x_retry_secret: Optional[str] = Header(None, alias="X-Retry-Secret"),
):
    """Process pending webhook delivery retries.

    This endpoint is meant to be called by an external cron job (e.g.,
    cron-job.org, GitHub Actions schedule, UptimeRobot). It picks up
    webhook logs with ``retry_status='pending'`` and ``next_retry_at``
    in the past, re-forwards them, and updates the log entries.

    Secured by the ``RETRY_ENDPOINT_SECRET`` setting as a shared secret in the
    ``X-Retry-Secret`` header. This prevents unauthorized callers from
    triggering retries.

    Returns:
        JSON with ``processed`` count and ``results`` list.
    """
    # Constant-time comparison avoids leaking validity via timing side-channels.
    if not settings.RETRY_ENDPOINT_SECRET or not compare_digest(
        x_retry_secret or "", settings.RETRY_ENDPOINT_SECRET
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    now = datetime.now(timezone.utc).isoformat()

    # Reap entries stranded in "retrying" (e.g. a worker that died mid-retry)
    # so they re-enter the "pending" pool and are not lost permanently.
    reaper_cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=_RETRY_CLAIM_STALE_SECONDS)
    ).isoformat()
    try:
        admin.table("webhook_logs").update({"retry_status": "pending"}).eq(
            "retry_status", "retrying"
        ).lt("updated_at", reaper_cutoff).execute()
    except Exception:
        logger.warning("Retry reaper failed")

    # Fetch pending retries that are due.
    pending = (
        admin.table("webhook_logs")
        .select(
            "*, routes!inner(destination_url, method, headers, transform_headers, transform_body_template)"
        )
        .eq("retry_status", "pending")
        .lte("next_retry_at", now)
        .lt("retry_count", _MAX_RETRIES)
        .gte("created_at", get_retry_window_cutoff())
        .limit(10)
        .execute()
    )

    results = []

    for log_entry in pending.data or []:
        route_info = log_entry.get("routes", {})
        log_id = log_entry["id"]
        retry_count = log_entry["retry_count"] + 1
        destination_url = route_info.get("destination_url", "")

        if not destination_url:
            new_status = "exhausted"
            next_retry = None
            result = (
                admin.table("webhook_logs")
                .update(
                    {
                        "retry_count": retry_count,
                        "retry_status": new_status,
                        "next_retry_at": next_retry,
                    }
                )
                .eq("id", log_id)
                .execute()
            )
            if not result.data:
                logger.warning(
                    "Retry mark-exhausted update failed for log_id=%s", log_id
                )
            results.append(
                {
                    "log_id": log_id,
                    "retry_count": retry_count,
                    "status_code": 0,
                    "outcome": new_status,
                }
            )
            continue

        # Claim this entry atomically: only transition a row that is still
        # "pending". Under concurrent cron runs / workers, the first claimer
        # wins; late claimers see no row and skip, preventing duplicate
        # deliveries. "retrying" is a valid value in the retry_status CHECK
        # constraint; "processing" is NOT and would cause the UPDATE to fail.
        claim_result = (
            admin.table("webhook_logs")
            .update({"retry_status": "retrying"})
            .eq("id", log_id)
            .eq("retry_status", "pending")
            .execute()
        )
        if not claim_result.data:
            logger.warning("Retry already claimed for log_id=%s, skipping", log_id)
            continue

        # Rebuild the body from stored request_body using original content_type.
        stored_body = log_entry.get("request_body", {})
        content_type = log_entry.get("content_type", "")
        body = b""

        if not stored_body:
            # Empty body is fine.
            pass
        elif "application/json" in content_type or isinstance(
            stored_body, (dict, list)
        ):
            body = json.dumps(stored_body).encode("utf-8")
        elif "application/x-www-form-urlencoded" in content_type:
            from urllib.parse import urlencode

            body = urlencode(stored_body).encode("utf-8")
        elif content_type in (
            "application/xml",
            "text/xml",
            "application/protobuf",
            "application/octet-stream",
        ):
            # Cannot reliably reconstruct these from jsonb; skip retry.
            new_status = "exhausted"
            next_retry = None
            result = (
                admin.table("webhook_logs")
                .update(
                    {
                        "retry_count": retry_count,
                        "retry_status": new_status,
                        "next_retry_at": next_retry,
                    }
                )
                .eq("id", log_id)
                .execute()
            )
            if not result.data:
                logger.warning("Retry exhaust update failed for log_id=%s", log_id)
            results.append(
                {
                    "log_id": log_id,
                    "retry_count": retry_count,
                    "status_code": 0,
                    "outcome": new_status,
                }
            )
            continue
        else:
            # Generic text fallback.
            body = str(stored_body).encode("utf-8")

        # Apply transformation if configured.
        forward_body = body
        transform_template = route_info.get("transform_body_template")
        if transform_template and isinstance(stored_body, dict):
            rendered = render_template(transform_template, stored_body)
            forward_body = rendered.encode("utf-8")

        outbound_headers = dict(route_info.get("headers", {}))
        transform_headers = route_info.get("transform_headers", {})
        if transform_headers:
            outbound_headers.update(transform_headers)

        status_code, response_body, response_headers = await forward_payload(
            method=route_info.get("method", "POST"),
            url=destination_url,
            body=forward_body,
            headers=outbound_headers,
        )

        # Determine outcome. Use the same retry predicate as the forward
        # path (should_retry) to stay consistent.
        if 200 <= status_code < 300:
            new_status = "succeeded"
            next_retry = None
        elif should_retry(status_code) and retry_count < _MAX_RETRIES:
            new_status = "pending"
            next_retry = calculate_next_retry(retry_count)
        else:
            # 4xx (except retryable 429) and exhausted attempts are terminal.
            new_status = "exhausted"
            next_retry = None

        result = (
            admin.table("webhook_logs")
            .update(
                {
                    "retry_count": retry_count,
                    "retry_status": new_status,
                    "status_code": status_code,
                    "next_retry_at": next_retry,
                }
            )
            .eq("id", log_id)
            .execute()
        )
        if not result.data:
            logger.warning("Retry status update failed for log_id=%s", log_id)

        # Insert into dead-letter queue if exhausted.
        if new_status == "exhausted":
            failure_result = (
                admin.table("webhook_failures")
                .insert(
                    {
                        "route_id": log_entry["route_id"],
                        "webhook_log_id": log_id,
                        "status_code": status_code,
                        "response_body": response_body[:_MAX_LOG_BODY_BYTES]
                        if response_body
                        else None,
                        "ip_address": log_entry.get("ip_address"),
                        "user_agent": log_entry.get("user_agent"),
                        "retry_count": retry_count,
                        "max_retries": _MAX_RETRIES,
                    }
                )
                .execute()
            )
            if not failure_result.data:
                logger.warning("Dead-letter insert failed for log_id=%s", log_id)

        # Update idempotency cache if key exists and response is successful.
        idempotency_key = log_entry.get("idempotency_key")
        if idempotency_key and status_code < 400:
            store_idempotency(
                log_entry["route_id"],
                idempotency_key,
                status_code,
                response_body,
                response_headers,
            )

        results.append(
            {
                "log_id": log_id,
                "retry_count": retry_count,
                "status_code": status_code,
                "outcome": new_status,
            }
        )

    logger.info("Processed %d retries", len(results))

    return {"processed": len(results), "results": results}


@router.post("/internal/cleanup")
async def cleanup(
    request: Request,
    x_retry_secret: Optional[str] = Header(None, alias="X-Retry-Secret"),
    keep_days: int | None = None,
):
    """Run periodic retention cleanup to bound database growth.

    Prunes expired PKCE verifiers, idempotency cache entries, rate-limit
    windows, and old webhook delivery logs (plus their dead-letter rows).

    Secured by the same ``RETRY_ENDPOINT_SECRET`` shared secret as
    ``/internal/process-retries`` (constant-time comparison). Intended to be
    invoked by a free scheduled job (e.g. a GitHub Actions cron) so no paid
    job-runner is required.

    Args:
        keep_days: How many days of webhook delivery history to retain.
            Clamped to the inclusive range [1, 365]; a non-positive value
            would otherwise compute a retention cutoff in the future and
            delete ALL history, while an unbounded value would disable
            retention entirely.

    Returns:
        JSON with the number of rows removed per cleanup step.
    """
    if not settings.RETRY_ENDPOINT_SECRET or not compare_digest(
        x_retry_secret or "", settings.RETRY_ENDPOINT_SECRET
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Fail safe on retention: never delete everything, never keep forever.
    keep_days = max(1, min(int(keep_days or settings.RETENTION_DAYS), 365))

    def _safe_count_rpc(fn_name: str, params: Optional[dict] = None) -> int:
        """Invoke a SQL cleanup function that returns a row count, tolerating missing functions."""
        try:
            result = admin.rpc(fn_name, params or {}).execute()
            if isinstance(result.data, list) and result.data:
                value = result.data[0]
                if isinstance(value, dict):
                    return int(next(iter(value.values())))
                return int(value)
            return 0
        except Exception:
            logger.warning("Cleanup step %s failed", fn_name)
            return 0

    def _safe_void_rpc(fn_name: str, params: Optional[dict] = None) -> bool:
        """Invoke a SQL cleanup function that returns void, tolerating missing functions."""
        try:
            admin.rpc(fn_name, params or {}).execute()
            return True
        except Exception:
            logger.warning("Cleanup step %s failed", fn_name)
            return False

    webhook_logs_removed = _safe_count_rpc(
        "cleanup_webhook_logs", {"p_keep_days": keep_days}
    )
    rate_limits_cleaned_count = _safe_void_rpc("cleanup_rate_limits")
    pkce_verifiers_cleaned_count = _safe_void_rpc("cleanup_pkce_verifiers")
    idempotency_cache_cleaned_count = _safe_void_rpc("cleanup_idempotency_cache")

    return {
        "webhook_logs_removed": webhook_logs_removed,
        # The remaining fields are booleans indicating success/failure of each
        # cleanup step, not row counts. They are named ``_cleaned_count`` for
        # API consistency but the value is ``True`` on success, ``False`` on
        # failure.
        "rate_limits_cleaned": rate_limits_cleaned_count,
        "pkce_verifiers_cleaned": pkce_verifiers_cleaned_count,
        "idempotency_cache_cleaned": idempotency_cache_cleaned_count,
        "keep_days": keep_days,
    }


def cleanup_rate_limits() -> bool:
    """Invoke the ``cleanup_rate_limits`` SQL function.

    Returns:
        ``True`` if the function executed without error, ``False`` otherwise.
    """
    try:
        admin.rpc("cleanup_rate_limits").execute()
        return True
    except Exception:
        logger.warning("cleanup_rate_limits failed")
        return False


def cleanup_pkce_verifiers() -> bool:
    """Invoke the ``cleanup_pkce_verifiers`` SQL function.

    Returns:
        ``True`` if the function executed without error, ``False`` otherwise.
    """
    try:
        admin.rpc("cleanup_pkce_verifiers").execute()
        return True
    except Exception:
        logger.warning("cleanup_pkce_verifiers failed")
        return False


def cleanup_idempotency_cache() -> bool:
    """Invoke the ``cleanup_idempotency_cache`` SQL function.

    Returns:
        ``True`` if the function executed without error, ``False`` otherwise.
    """
    try:
        admin.rpc("cleanup_idempotency_cache").execute()
        return True
    except Exception:
        logger.warning("cleanup_idempotency_cache failed")
        return False


@router.get("/internal/health/outbound")
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
    target = "https://www.google.com/generate_204"
    start = time.perf_counter()
    try:
        response = await client.head(target, timeout=_FORWARD_TIMEOUT_SECONDS)
        duration_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "healthy",
            "target": target,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.warning("Outbound health check failed: %s", exc)
        return {
            "status": "unhealthy",
            "target": target,
            "error": str(exc),
            "duration_ms": duration_ms,
        }
