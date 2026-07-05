"""Core webhook forwarding engine.

Receives webhooks, validates them, looks up destination URLs in Supabase,
forwards payloads, and logs delivery results. Supports:

* HMAC signature verification (per-route ``webhook_secret``)
* Per-route configurable rate limiting
* Idempotency keys to prevent duplicate deliveries
* Payload transformation via dot-notation templates
* DB-based retry queue for failed deliveries
"""

import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.database import admin, bump_route_metrics_atomic

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Proxy Engine"])

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

_RETRY_BACKOFF_BASE_SECONDS = 5
"""Base delay for exponential backoff: delay = base * (2 ^ retry_count)."""

# Regex for template placeholders: {{field.path}}
_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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
        return forwarded.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"


def parse_payload(body: bytes, content_type: str) -> dict:
    """Parse the incoming request body into a dictionary.

    Supports JSON and form-urlencoded payloads. Falls back to an empty
    dict on parse failure.

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
        try:
            return json.loads(body)
        except Exception:
            return {k: v[0] for k, v in parse_qs(body.decode()).items()}
    except Exception:
        return {}


def resolve_dot_path(data: Any, path: str) -> Any:
    """Resolve a dot-separated path against a nested data structure.

    Supports dict keys and integer list indices. Returns ``None`` if any
    segment is missing rather than raising.

    Examples::

        resolve_dot_path({"a": {"b": 1}}, "a.b")  # → 1
        resolve_dot_path({"items": [10, 20]}, "items.0")  # → 10
        resolve_dot_path({}, "missing.key")  # → None

    Args:
        data: The root dict or list.
        path: Dot-separated field path.

    Returns:
        The resolved value or ``None``.
    """
    current = data
    for segment in path.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(segment)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def render_template(template: str, payload: dict) -> str:
    """Render a template string by replacing ``{{field.path}}`` placeholders.

    Uses :func:`resolve_dot_path` for nested access. Missing fields are
    replaced with an empty string.

    Args:
        template: The template string with ``{{...}}`` placeholders.
        payload: The parsed webhook payload.

    Returns:
        The rendered string.
    """
    def replacer(match: re.Match) -> str:
        path = match.group(1)
        value = resolve_dot_path(payload, path)
        if value is None:
            return ""
        return str(value)

    return _TEMPLATE_PATTERN.sub(replacer, template)


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


def enforce_rate_limit(route_id: str, client_ip: str, max_requests: int) -> None:
    """Check and increment the per-IP rate limit for a route.

    Uses the atomic ``increment_rate_limit`` RPC to avoid race conditions.

    Args:
        route_id: The UUID of the route being hit.
        client_ip: The IP address to track.
        max_requests: Maximum allowed requests within the window.

    Raises:
        HTTPException: 429 if the client has exceeded the rate limit.
    """
    window_start_cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=_RATE_LIMIT_WINDOW_SECONDS)
    ).isoformat()

    try:
        result = (
            admin.rpc(
                "increment_rate_limit",
                {
                    "p_route_id": route_id,
                    "p_ip": client_ip,
                    "p_window_start": window_start_cutoff,
                    "p_max_requests": max_requests,
                },
            )
            .execute()
        )

        if result.data:
            row = result.data[0]
            if not row.get("success"):
                raise HTTPException(status_code=429, detail="Too many requests")
            return
    except HTTPException:
        raise
    except Exception:
        logger.exception("Rate limit check failed for route %s", route_id)

    # Fallback: deny if the RPC path failed to avoid bypassing the limit.
    raise HTTPException(status_code=429, detail="Too many requests")


def check_idempotency(route_id: str, idempotency_key: str) -> Optional[dict]:
    """Check if a request with this idempotency key was already processed.

    Args:
        route_id: The route UUID.
        idempotency_key: The idempotency key from the request header.

    Returns:
        The cached response dict if found and fresh (< 24h), or ``None``.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=24)
    ).isoformat()

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
        logger.exception("Failed to store idempotency cache entry")


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
    truncated_body = (
        response_body[:_MAX_LOG_BODY_BYTES] if response_body else None
    )

    try:
        result = admin.table("webhook_logs").insert(
            {
                "route_id": route_id,
                "status_code": status_code,
                "request_body": (
                    payload if isinstance(payload, (dict, list)) else str(payload)
                ),
                "response_body": truncated_body,
                "response_headers": response_headers,
                "ip_address": client_ip,
                "user_agent": user_agent,
                "duration_ms": duration_ms,
                "content_type": content_type,
                "idempotency_key": idempotency_key,
                "retry_status": retry_status,
                "next_retry_at": next_retry_at,
            }
        ).execute()

        if result.data:
            return result.data[0].get("id")
    except Exception:
        logger.exception("Failed to log delivery for route_id=%s", route_id)

    return None


def _should_retry(status_code: int) -> bool:
    """Determine if a delivery should be retried based on status code.

    Retries only on reversible server errors: 502, 503, 504.

    Args:
        status_code: The HTTP status from the destination.

    Returns:
        ``True`` if the delivery should be retried.
    """
    return status_code in (429, 502, 503, 504)


def _calculate_next_retry(retry_count: int) -> str:
    """Calculate the next retry timestamp with exponential backoff.

    Args:
        retry_count: The current retry attempt (0-based).

    Returns:
        ISO 8601 timestamp of the next retry.
    """
    delay = _RETRY_BACKOFF_BASE_SECONDS * (2 ** retry_count)
    # Cap at 5 minutes.
    delay = min(delay, 300)
    return (
        datetime.now(timezone.utc) + timedelta(seconds=delay)
    ).isoformat()


# ---------------------------------------------------------------------------
# Public proxy endpoint
# ---------------------------------------------------------------------------
@router.post("/v1/route/{slug}")
async def proxy_webhook(
    slug: str,
    request: Request,
    user_agent: Optional[str] = Header(None),
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

    # Honeypot — drop obvious spam silently.
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
        raise HTTPException(
            status_code=404, detail="Active routing link not found."
        )

    route = route_result.data[0]

    # --- Signature verification ---
    webhook_secret = route.get("webhook_secret")
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

    # --- Idempotency check ---
    if idempotency_key:
        cached = check_idempotency(route["id"], idempotency_key)
        if cached:
            return cached

    # --- Rate limiting (per-route config) ---
    route_rate_limit = route.get("rate_limit", _DEFAULT_RATE_LIMIT)
    enforce_rate_limit(route["id"], client_ip, route_rate_limit)

    # --- Payload transformation ---
    forward_body = body
    transform_template = route.get("transform_body_template")
    if transform_template:
        rendered = render_template(transform_template, payload)
        forward_body = rendered.encode("utf-8")

    # Merge route-level transform headers with configured headers.
    outbound_headers = dict(route.get("headers", {}))
    transform_headers = route.get("transform_headers", {})
    if transform_headers:
        outbound_headers.update(transform_headers)

    # --- Forward ---
    destination = route["destination_url"]
    method = route.get("method", "POST")

    status_code, response_body, response_headers = await forward_payload(
        method=method,
        url=destination,
        body=forward_body,
        headers=outbound_headers,
    )

    duration_ms = int((time.perf_counter() - start_time) * 1000)

    # --- Determine retry status ---
    retry_status = "none"
    next_retry_at = None
    if _should_retry(status_code):
        retry_status = "pending"
        next_retry_at = _calculate_next_retry(0)

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
    if idempotency_key:
        store_idempotency(
            route["id"],
            idempotency_key,
            status_code,
            response_body,
            response_headers,
        )

    # --- Update route metrics ---
    bump_route_metrics_atomic(route["id"])

    return {
        "status": "forwarded",
        "destination_status": status_code,
    }


# ---------------------------------------------------------------------------
# Retry processing endpoint (called by external cron)
# ---------------------------------------------------------------------------
_RETRY_SECRET_HEADER = "X-Retry-Secret"


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
    valid_secrets = [settings.RETRY_ENDPOINT_SECRET, settings.API_KEY_SALT]
    if x_retry_secret not in valid_secrets or not x_retry_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")

    now = datetime.now(timezone.utc).isoformat()

    # Fetch pending retries that are due.
    pending = (
        admin.table("webhook_logs")
        .select("*, routes!inner(destination_url, method, headers, transform_headers, transform_body_template)")
        .eq("retry_status", "pending")
        .lte("next_retry_at", now)
        .lt("retry_count", _MAX_RETRIES)
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
            admin.table("webhook_logs").update(
                {
                    "retry_count": retry_count,
                    "retry_status": new_status,
                    "next_retry_at": next_retry,
                }
            ).eq("id", log_id).execute()
            results.append(
                {
                    "log_id": log_id,
                    "retry_count": retry_count,
                    "status_code": 0,
                    "outcome": new_status,
                }
            )
            continue

        # Mark as retrying.
        admin.table("webhook_logs").update(
            {"retry_status": "retrying"}
        ).eq("id", log_id).execute()

        # Rebuild the body from stored request_body using original content_type.
        stored_body = log_entry.get("request_body", {})
        content_type = log_entry.get("content_type", "")
        body = b""
        if stored_body:
            if "application/json" in content_type or isinstance(stored_body, dict):
                body = json.dumps(stored_body).encode("utf-8")
            elif "application/x-www-form-urlencoded" in content_type:
                from urllib.parse import urlencode
                body = urlencode(stored_body).encode("utf-8")
            else:
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

        # Determine outcome.
        if status_code < 500:
            new_status = "succeeded"
            next_retry = None
        elif retry_count >= _MAX_RETRIES:
            new_status = "exhausted"
            next_retry = None
        else:
            new_status = "pending"
            next_retry = _calculate_next_retry(retry_count)

        admin.table("webhook_logs").update(
            {
                "retry_count": retry_count,
                "retry_status": new_status,
                "status_code": status_code,
                "next_retry_at": next_retry,
            }
        ).eq("id", log_id).execute()

        # Update idempotency cache if key exists.
        idempotency_key = log_entry.get("idempotency_key")
        if idempotency_key:
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
