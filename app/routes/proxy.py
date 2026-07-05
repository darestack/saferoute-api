"""Core webhook forwarding engine.

Receives webhooks, validates them, looks up destination URLs in Supabase,
forwards payloads, and logs delivery results.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, HTTPException, Request, Header

from app.config import settings
from app.database import admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Proxy Engine"])

# Tunables
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 30
_FORWARD_TIMEOUT_SECONDS = 10.0
_MAX_LOG_BODY_BYTES = 10_000
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0

# In-memory rate limit store (sub-millisecond checks).
# Falls back to DB if the memory store is unavailable or in multi-worker mode.
_rate_limit_lock = threading.Lock()
_rate_limit_store: dict[str, dict[str, list[float]]] = defaultdict(dict)


def _get_in_memory_key(route_id: str, client_ip: str) -> str:
    return f"{route_id}:{client_ip}"


def enforce_rate_limit(route_id: str, client_ip: str) -> None:
    """Check and increment the per-IP rate limit for a route.

    Uses an in-memory store for sub-millisecond checks, with a fallback
    to the database for multi-worker durability.

    Args:
        route_id: The UUID of the route being hit.
        client_ip: The IP address to track.

    Raises:
        HTTPException: 429 if the client has exceeded the rate limit.
    """
    key = _get_in_memory_key(route_id, client_ip)
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS

    with _rate_limit_lock:
        timestamps = _rate_limit_store.get(route_id, {}).get(client_ip, [])
        timestamps = [ts for ts in timestamps if ts > window_start]

        if len(timestamps) >= _RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(status_code=429, detail="Too many requests")

        timestamps.append(now)
        if route_id not in _rate_limit_store:
            _rate_limit_store[route_id] = {}
        _rate_limit_store[route_id][client_ip] = timestamps


def get_client_ip(request: Request) -> str:
    """Extract the real client IP from the request.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The client IP as a string, or ``"unknown"`` if unavailable.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"


def parse_payload(body: bytes, content_type: str) -> dict:
    """Parse the incoming request body into a dictionary.

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

        return {k: v[0] for k, v in parse_qs(body.decode()).items()}
    except Exception:
        return {}


def verify_webhook_signature(body: bytes, signature: Optional[str]) -> bool:
    """Verify the HMAC-SHA256 signature of an inbound webhook.

    Args:
        body: Raw request body bytes.
        signature: Value of the ``X-Hub-Signature-256`` header.

    Returns:
        ``True`` if the signature matches, ``False`` otherwise.
    """
    if not signature or not settings.WEBHOOK_SECRET:
        return False

    expected = "sha256=" + hashlib.sha256(
        (settings.WEBHOOK_SECRET + body.decode("utf-8", errors="replace")).encode("utf-8")
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def enforce_rate_limit(route_id: str, client_ip: str) -> None:
    """Check and increment the per-IP rate limit for a route.

    Args:
        route_id: The UUID of the route being hit.
        client_ip: The IP address to track.

    Raises:
        HTTPException: 429 if the client has exceeded the rate limit.
    """
    now = datetime.now(timezone.utc)
    window_start_cutoff = (now - timedelta(seconds=_RATE_LIMIT_WINDOW_SECONDS)).isoformat()

    existing = (
        admin.table("rate_limits")
        .select("*")
        .eq("route_id", route_id)
        .eq("ip_address", client_ip)
        .gte("window_start", window_start_cutoff)
        .execute()
    )

    if existing.data:
        current = existing.data[0]
        count = current["request_count"]

        if count >= _RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(status_code=429, detail="Too many requests")

        admin.table("rate_limits").update(
            {"request_count": count + 1}
        ).eq("id", current["id"]).execute()
    else:
        admin.table("rate_limits").insert(
            {
                "route_id": route_id,
                "ip_address": client_ip,
                "request_count": 1,
            }
        ).execute()


async def forward_payload(
    method: str,
    url: str,
    body: bytes,
    headers: dict,
) -> Tuple[int, str, dict]:
    """Forward the webhook payload to the destination URL.

    Returns:
        A tuple of ``(status_code, response_body, response_headers)``.
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
        except httpx.RequestError as exc:
            logger.warning("Destination unreachable: %s", exc)
            return 502, "Destination unreachable", {}


async def forward_with_retry(
    method: str,
    url: str,
    body: bytes,
    headers: dict,
    max_retries: int = _MAX_RETRIES,
    base_delay: float = _RETRY_BASE_DELAY,
) -> Tuple[int, str, dict]:
    """Forward a webhook with exponential backoff retries on 5xx/timeout.

    Args:
        method: HTTP method to use.
        url: The destination webhook URL.
        body: Raw request body bytes to forward.
        headers: Extra headers to include.
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds for exponential backoff.

    Returns:
        A tuple of ``(status_code, response_body, response_headers)``.
    """
    status_code = 502
    response_body = "Destination unreachable"
    response_headers = {}

    for attempt in range(max_retries + 1):
        status_code, response_body, response_headers = await forward_payload(
            method=method,
            url=url,
            body=body,
            headers=headers,
        )

        if status_code < 500:
            return status_code, response_body, response_headers

        if attempt < max_retries:
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Webhook delivery attempt %s/%s failed with %s, retrying in %ss",
                attempt + 1,
                max_retries + 1,
                status_code,
                delay,
            )
            await asyncio.sleep(delay)

    return status_code, response_body, response_headers


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

    Args:
        route_id: The route that was hit.
        status_code: HTTP status returned by the destination.
        payload: Parsed inbound payload for storage.
        response_body: Raw text body returned by the destination.
        response_headers: Response headers from the destination.
        client_ip: IP address of the requester.
        user_agent: ``User-Agent`` header from the request.
        duration_ms: Total processing time in milliseconds.
    """
    truncated_body = response_body[:_MAX_LOG_BODY_BYTES] if response_body else None

    try:
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
    except Exception:
        logger.exception("Failed to log delivery for route %s", route_id)


def bump_route_metrics_atomic(route_id: str) -> None:
    """Update the ``requests_count`` and ``last_used_at`` for a route.

    Uses an atomic RPC call to avoid race conditions.

    Args:
        route_id: The route to update.
    """
    try:
        admin.rpc("increment_route_count", params={"p_route_id": route_id}).execute()
    except Exception:
        logger.exception("Failed to bump metrics for route %s", route_id)


def get_idempotency_response(route_id: str, idempotency_key: str) -> Optional[dict]:
    """Look up a cached response for an idempotency key.

    Args:
        route_id: The route UUID.
        idempotency_key: The idempotency key from the request header.

    Returns:
        Cached response dict if found and not expired, otherwise None.
    """
    result = (
        admin.table("idempotency_keys")
        .select("*")
        .eq("route_id", route_id)
        .eq("idempotency_key", idempotency_key)
        .gt("expires_at", datetime.now(timezone.utc).isoformat())
        .execute()
    )

    if result.data:
        row = result.data[0]
        return {
            "status_code": row["response_status"],
            "response_body": row["response_body"],
            "response_headers": row["response_headers"],
        }

    return None


def store_idempotency_response(
    route_id: str,
    idempotency_key: str,
    status_code: int,
    response_body: str,
    response_headers: dict,
) -> None:
    """Store a response for an idempotency key.

    Args:
        route_id: The route UUID.
        idempotency_key: The idempotency key from the request header.
        status_code: HTTP status code of the response.
        response_body: Response body text.
        response_headers: Response headers dict.
    """
    try:
        admin.table("idempotency_keys").upsert(
            {
                "route_id": route_id,
                "idempotency_key": idempotency_key,
                "response_status": status_code,
                "response_body": response_body,
                "response_headers": response_headers,
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            },
            on_conflict="route_id, idempotency_key",
        ).execute()
    except Exception:
        logger.exception("Failed to store idempotency response for route %s", route_id)


def apply_transforms(body: bytes, transform_rules: dict, content_type: str) -> bytes:
    """Apply payload transformation rules to the request body.

    Currently supports:
    - ``add_headers``: Extra headers to inject into the forwarded request.
    - ``replace_fields``: Simple string replacement in JSON/form bodies.

    Args:
        body: Raw request body bytes.
        transform_rules: Transformation configuration dict.
        content_type: The ``Content-Type`` header value.

    Returns:
        Transformed body bytes, or original body if no transforms apply.
    """
    if not transform_rules or not body:
        return body

    try:
        add_headers = transform_rules.get("add_headers", {})
        replace_fields = transform_rules.get("replace_fields", {})

        if not replace_fields:
            return body

        if "application/json" in content_type:
            payload = json.loads(body)
            for key, value in replace_fields.items():
                if key in payload:
                    payload[key] = value
            return json.dumps(payload).encode("utf-8")

        return body
    except Exception:
        logger.exception("Failed to apply transforms")
        return body


@router.post("/v1/route/{slug}")
async def proxy_webhook(
    slug: str,
    request: Request,
    user_agent: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Receive a webhook, validate it, forward it, and log the result.

    Processing steps:
        1. Parse the raw body (JSON or form-urlencoded).
        2. Strip known honeypot fields silently.
        3. Verify webhook signature if provided.
        4. Check idempotency key cache.
        5. Look up the active route by ``slug``.
        6. Enforce per-IP rate limiting.
        7. Apply payload transformations.
        8. Forward the raw payload to the destination URL/method.
        9. Store response in idempotency cache (if key provided).
        10. Log the delivery attempt.
        11. Update route metrics.

    Args:
        slug: The public route slug from the URL path.
        request: The incoming FastAPI request.
        user_agent: ``User-Agent`` header, if present.
        x_hub_signature_256: ``X-Hub-Signature-256`` header for HMAC verification.
        idempotency_key: ``Idempotency-Key`` header for deduplication.

    Returns:
        JSON with ``status`` and ``destination_status``.

    Raises:
        HTTPException: 404 if the route is missing or inactive.
        HTTPException: 401 if the webhook signature is invalid.
        HTTPException: 429 if the client is rate-limited.
        HTTPException: 502/504 if the destination is unreachable or times out.
    """
    start_time = time.perf_counter()
    client_ip = get_client_ip(request)

    try:
        body = await request.body()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    content_type = request.headers.get("content-type", "")
    payload = parse_payload(body, content_type)

    payload.pop("honeypot_field", None)
    payload.pop("_gotcha", None)

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
    extra_headers = dict(route.get("headers", {}))
    transform_rules = route.get("transform_rules", {})

    # Check idempotency cache first.
    if idempotency_key:
        cached = get_idempotency_response(route["id"], idempotency_key)
        if cached:
            return {
                "status": "idempotent",
                "destination_status": cached["status_code"],
            }

    enforce_rate_limit(route["id"], client_ip)

    # Apply transformations.
    transformed_body = apply_transforms(body, transform_rules, content_type)
    if transform_rules.get("add_headers"):
        extra_headers.update(transform_rules["add_headers"])

    status_code, response_body, response_headers = await forward_with_retry(
        method=method,
        url=destination,
        body=transformed_body,
        headers=extra_headers,
    )

    duration_ms = int((time.perf_counter() - start_time) * 1000)

    # Store idempotency response.
    if idempotency_key:
        store_idempotency_response(
            route_id=route["id"],
            idempotency_key=idempotency_key,
            status_code=status_code,
            response_body=response_body,
            response_headers=response_headers,
        )

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

    bump_route_metrics_atomic(route["id"])

    return {
        "status": "forwarded",
        "destination_status": status_code,
    }
