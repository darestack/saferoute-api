"""Authentication and route management endpoints.

Provides JWT-based authentication, route CRUD, API key rotation,
webhook log retrieval, and route analytics.
"""

from __future__ import annotations
import asyncio
import inspect
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional, cast

import httpx
import jwt
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.crypto import encrypt_webhook_secret
from app.database import (
    admin,
    clear_api_key_cache_for_route,
    execute_query,
    generate_api_key,
)
from app.repositories import route_repository
from app.routes.proxy import (
    clear_route_cache_for_route,
    clear_circuit_breaker_for_url,
    forward_payload,
    log_delivery,
)
from app.services.retry_processor import rebuild_retry_body
from app.models import (
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    RouteCreateResponse,
    RouteStatsResponse,
    RetryQueuedResponse,
    User,
    UserCreate,
    WebhookLogResponse,
    WebhookFailureResponse,
    WebhookFailuresResponse,
)
from app.utils.routes import get_owned_route_or_404, route_to_response
from app.utils.security import (
    safe_error_detail,
    generate_slug,
    validate_destination_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Authentication & Routes"])

__all__ = [
    "router",
    "close_jwks_client",
]

# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------
_JWKS_CACHE_TTL_SECONDS = 300
_jwks_cache: Optional[dict] = None
_jwks_cache_expiry: float = 0.0
_jwks_lock = asyncio.Lock()
_jjwks_client: Optional[httpx.AsyncClient] = None


def _get_jwks_client() -> httpx.AsyncClient:
    """Return the shared JWKS HTTP client, creating it on first call."""
    global _jjwks_client
    if _jjwks_client is None or _jjwks_client.is_closed:
        _jjwks_client = httpx.AsyncClient(timeout=5.0)
    return _jjwks_client


async def close_jwks_client() -> None:
    """Close the shared JWKS HTTP client on application shutdown."""
    global _jjwks_client
    if _jjwks_client is not None and not _jjwks_client.is_closed:
        await _jjwks_client.aclose()
        _jjwks_client = None


async def _get_cached_jwks() -> dict:
    """Fetch Supabase JWKS with a TTL-based cache."""
    global _jwks_cache, _jwks_cache_expiry

    now = time.monotonic()
    if _jwks_cache is not None and now < _jwks_cache_expiry:
        return _jwks_cache

    async with _jwks_lock:
        now = time.monotonic()
        if _jwks_cache is not None and now < _jwks_cache_expiry:
            return _jwks_cache

        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        try:
            response = await _get_jwks_client().get(
                jwks_url,
                headers={"apikey": settings.SUPABASE_KEY},
            )
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_expiry = now + _JWKS_CACHE_TTL_SECONDS
            return _jwks_cache
        except Exception:
            logger.exception("Failed to fetch JWKS from %s", jwks_url)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to validate token at this time",
            )


# ---------------------------------------------------------------------------
# User cache (L1 in-memory + L2 PostgreSQL)
# ---------------------------------------------------------------------------
from collections import OrderedDict  # noqa: E402
from app.services.cache import DistributedCache  # noqa: E402

_USER_CACHE_TTL_SECONDS = 300
_USER_CACHE_MAX_SIZE = 1000
_user_cache = DistributedCache(
    max_size=_USER_CACHE_MAX_SIZE,
    default_ttl=_USER_CACHE_TTL_SECONDS,
)

# In-flight user fetches: prevents duplicate DB calls when many concurrent
# requests miss the cache for the same user_id.
_USER_CACHE_FILLS_MAX_ENTRIES = 1_000
_user_cache_fills: "OrderedDict[str, tuple[asyncio.Future, float]]" = OrderedDict()
_user_cache_fills_lock = asyncio.Lock()


def _user_to_dict(user: User) -> dict[str, Any]:
    """Serialize a User to a JSON-compatible dict."""
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _dict_to_user(data: dict[str, Any]) -> User:
    """Deserialize a dict back to a User model."""
    return User(
        id=data["id"],
        email=data["email"],
        full_name=data.get("full_name"),
        created_at=data.get("created_at"),
    )


async def _get_cached_user(user_id: str) -> Optional[User]:
    """Return a cached User if available and fresh."""
    raw = await _user_cache.get(user_id)
    if raw is not None:
        if isinstance(raw, dict):
            return _dict_to_user(raw)
        return cast(User, raw)
    return None


async def _cache_user(user: User) -> None:
    """Store a User in the cache with TTL and FIFO eviction."""
    await _user_cache.set(user.id, _user_to_dict(user), ttl=_USER_CACHE_TTL_SECONDS)


async def _fetch_and_cache_user(user_id: str) -> User:
    """Fetch a user from Supabase Auth and cache the result.

    Uses single-flight semantics to avoid duplicate DB calls when many
    concurrent requests miss the cache for the same user_id.
    """
    cached = await _get_cached_user(user_id)
    if cached:
        return cached

    async with _user_cache_fills_lock:
        existing = _user_cache_fills.get(user_id)
        if existing is not None:
            return await existing[0]  # type: ignore[no-any-return]

        fut = asyncio.get_running_loop().create_future()
        _user_cache_fills[user_id] = (fut, time.monotonic())

        # Evict oldest entries if over limit to prevent memory leak.
        while len(_user_cache_fills) > _USER_CACHE_FILLS_MAX_ENTRIES:
            _evict_key, (_evict_fut, _evict_ts) = _user_cache_fills.popitem(last=False)
            if not _evict_fut.done():
                _evict_fut.cancel()

    try:
        # Perform the blocking DB call outside the lock to avoid stalling
        # concurrent cache readers/writers.
        result = await asyncio.to_thread(admin.auth.admin.get_user_by_id, user_id)
        if inspect.isawaitable(result):
            result = await result

        if not result.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        user = User(
            id=result.user.id,
            email=result.user.email or "",
            full_name=getattr(result.user, "full_name", None),
            created_at=result.user.created_at,
        )

        # Cache the user after the DB call completes.
        # Double-check in case another coroutine cached the same user
        # while we were waiting for the DB response.
        cached = await _user_cache.get(user_id)
        if cached is not None:
            user = cast(User, cached)
            fut.set_result(user)
            return user

        await _user_cache.set(
            user.id, _user_to_dict(user), ttl=_USER_CACHE_TTL_SECONDS
        )
        fut.set_result(user)
        return user
    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
            fut.exception()
        raise
    finally:
        _user_cache_fills.pop(user_id, None)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
async def get_current_user_from_jwt(
    authorization: Optional[str] = Header(None),
) -> User:
    """Return the current authenticated user from a JWT Bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or not parts[1]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
        )
    token_str = parts[1]

    try:
        jwks = await _get_cached_jwks()

        unverified_header = jwt.get_unverified_header(token_str)
        key_id = unverified_header.get("kid")
        public_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == key_id:
                try:
                    public_key = RSAAlgorithm.from_jwk(key)
                except Exception:
                    public_key = ECAlgorithm.from_jwk(key)
                break

        if not public_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: signing key not found",
            )

        payload = jwt.decode(
            token_str,
            public_key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
            issuer=f"{settings.SUPABASE_URL}/auth/v1",
        )

        user_id = payload.get("sub")
        email = payload.get("email")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID",
            )

        user = await _fetch_and_cache_user(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        # Prefer the cached DB email, falling back to the JWT claim when the
        # cached profile has no email (e.g. just-created account).
        return User(
            id=user.id,
            email=user.email or email or "",
            full_name=user.full_name,
            created_at=user.created_at,
        )

    except HTTPException:
        raise
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    except Exception:
        logger.exception("Token validation failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed",
        )


# ---------------------------------------------------------------------------
# Deprecated email/password auth
# ---------------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_410_GONE)
async def register_user(credentials: UserCreate):
    """Register (deprecated). Use OAuth instead."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Email/password registration is deprecated. "
        "Use /auth/oauth/google or /auth/oauth/github instead.",
    )


@router.post("/login", status_code=status.HTTP_410_GONE)
async def login_user(credentials: UserCreate):
    """Login (deprecated). Use OAuth instead."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Email/password login is deprecated. "
        "Use /auth/oauth/google or /auth/oauth/github instead.",
    )


# ---------------------------------------------------------------------------
# Session / profile
# ---------------------------------------------------------------------------
@router.get("/me", response_model=User)
async def get_me(current_user: User = Depends(get_current_user_from_jwt)):
    """Return the currently authenticated user's profile."""
    return current_user


# ---------------------------------------------------------------------------
# Route CRUD
# ---------------------------------------------------------------------------
@router.post(
    "/routes",
    response_model=RouteCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_route(
    route_data: RouteCreate,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Create a new proxy route for the authenticated user.

    Generates a public ``slug`` and a unique API key. The full API key
    is returned only once — store it securely.
    """
    slug = generate_slug(route_data.name)
    full_key, key_prefix, key_hash = generate_api_key()

    destination_url = str(route_data.destination_url)
    try:
        validate_destination_url(destination_url, resolve_dns=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    insert_data = {
        "user_id": current_user.id,
        "name": route_data.name,
        "slug": slug,
        "destination_url": destination_url,
        "method": route_data.method,
        "headers": route_data.headers,
        "api_key_prefix": key_prefix,
        "api_key_hash": key_hash,
        "rate_limit": route_data.rate_limit,
        "transform_headers": route_data.transform_headers,
    }

    if route_data.webhook_secret:
        insert_data["webhook_secret"] = encrypt_webhook_secret(
            route_data.webhook_secret
        )
    if route_data.webhook_secrets:
        insert_data["webhook_secrets"] = [
            encrypt_webhook_secret(secret) for secret in route_data.webhook_secrets
        ]
    if route_data.transform_body_template:
        insert_data["transform_body_template"] = route_data.transform_body_template

    try:
        route = await route_repository.create(insert_data)
        return RouteCreateResponse(**route_to_response(route, api_key=full_key))
    except HTTPException:
        raise
    except Exception as exc:
        if (
            getattr(exc, "code", None) == "23505"
            or "unique" in str(exc).lower()
            or "duplicate" in str(exc).lower()
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A route with this identifier already exists",
            )
        logger.exception("Failed to create route")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_detail(exc),
        )


@router.get("/routes", response_model=list[RouteResponse])
async def list_routes(
    current_user: User = Depends(get_current_user_from_jwt),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List all routes owned by the authenticated user (paginated)."""
    routes = await route_repository.list_by_user(current_user.id, limit, offset)
    return [RouteResponse(**route_to_response(row)) for row in routes]


@router.get("/routes/{route_id}", response_model=RouteResponse)
async def get_route(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Retrieve a single route by its internal UUID."""
    route = await route_repository.find_by_id(route_id, current_user.id)
    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found",
        )

    return RouteResponse(**route_to_response(route))


@router.put("/routes/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: str,
    route_data: RouteUpdate,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Update an existing route's configuration.

    When ``name`` is updated, the ``slug`` is regenerated.
    """
    updates = route_data.model_dump(exclude_none=True)

    if "destination_url" in updates:
        updates["destination_url"] = str(updates["destination_url"])
        try:
            validate_destination_url(updates["destination_url"], resolve_dns=True)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    if updates.pop("clear_webhook_secret", False):
        if updates.get("webhook_secret"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot clear and set webhook_secret in the same request",
            )
        updates["webhook_secret"] = None

    if "name" in updates:
        updates["slug"] = generate_slug(updates["name"])

    if "slug" in updates:
        if await route_repository.slug_exists_for_other_route(
            updates["slug"], route_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Slug already in use",
            )

    if "webhook_secrets" in updates and updates["webhook_secrets"]:
        updates["webhook_secrets"] = [
            encrypt_webhook_secret(secret) for secret in updates["webhook_secrets"]
        ]
    elif updates.get("webhook_secret"):
        # Single secret update without array — migrate to array format
        updates["webhook_secrets"] = [
            encrypt_webhook_secret(updates.pop("webhook_secret"))
        ]
    if "webhook_secret" in updates and updates["webhook_secret"]:
        updates["webhook_secret"] = encrypt_webhook_secret(updates["webhook_secret"])

    # Fetch the current slug and destination up front so a rename or
    # destination change can evict both old and new cache entries and reset
    # circuit breakers (see cache invalidation below).
    old_route_row = await route_repository.find_by_id(route_id, current_user.id)
    if not old_route_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found",
        )
    old_slug = old_route_row.get("slug")

    try:
        result = await route_repository.update(route_id, current_user.id, updates)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Route not found",
            )

        # Drop the cached proxy rows so the next webhook sees the new config
        # (destination, secret, headers, transforms, is_active, ...). On a
        # rename the OLD slug must also be evicted, otherwise the previous
        # public URL keeps working (serving the renamed route) for up to the
        # 30s cache TTL.
        new_slug = result["slug"]
        await clear_route_cache_for_route(new_slug)
        if old_slug and old_slug != new_slug:
            await clear_route_cache_for_route(old_slug)

        # Reset circuit breakers for old and new destinations so a previously
        # open circuit does not block traffic after a destination change.
        old_destination = old_route_row.get("destination_url")
        new_destination = result.get("destination_url")
        if old_destination and old_destination != new_destination:
            await clear_circuit_breaker_for_url(old_destination)
        if new_destination:
            await clear_circuit_breaker_for_url(new_destination)

        return RouteResponse(**route_to_response(result))
    except HTTPException:
        raise
    except Exception as exc:
        if (
            getattr(exc, "code", None) == "23505"
            or "unique" in str(exc).lower()
            or "duplicate" in str(exc).lower()
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Slug already in use",
            )
        logger.exception("Failed to update route %s", route_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_detail(exc),
        )


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Delete a route owned by the authenticated user."""
    result = await execute_query(
        admin.table("routes").delete().eq("id", route_id).eq("user_id", current_user.id)
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found",
        )

    # Evict the deleted route from the proxy cache so it stops accepting
    # traffic immediately rather than serving the stale cached row.
    await clear_route_cache_for_route(result.data[0]["slug"])
    await clear_circuit_breaker_for_url(result.data[0]["destination_url"])

    return None


@router.post("/routes/{route_id}/rotate-key", response_model=RouteCreateResponse)
async def rotate_api_key(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Rotate the API key for a route. Returns the new key once."""
    full_key, key_prefix, key_hash = generate_api_key()

    try:
        result = await execute_query(
            admin.table("routes")
            .update(
                {
                    "api_key_prefix": key_prefix,
                    "api_key_hash": key_hash,
                }
            )
            .eq("id", route_id)
            .eq("user_id", current_user.id)
        )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Route not found",
            )

        await clear_api_key_cache_for_route(route_id)
        # The route's API key changed; also drop the cached proxy row so the
        # new key is reflected on the next request.
        await clear_route_cache_for_route(result.data[0]["slug"])
        route = result.data[0]
        return RouteCreateResponse(**route_to_response(route, api_key=full_key))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to rotate API key for route %s", route_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_detail(exc),
        )


# ---------------------------------------------------------------------------
# Webhook logs
# ---------------------------------------------------------------------------
@router.get(
    "/routes/{route_id}/logs",
    response_model=list[WebhookLogResponse],
)
async def list_route_logs(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List webhook delivery logs for a route (newest first, paginated)."""
    await get_owned_route_or_404(admin, route_id, current_user.id, columns="id")

    result = await execute_query(
        admin.table("webhook_logs")
        .select("*")
        .eq("route_id", route_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )

    return [WebhookLogResponse(**row) for row in result.data]


@router.delete("/routes/{route_id}/logs", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route_logs(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Delete all webhook logs for a route.

    This is useful for clearing old delivery history to free up database
    space or remove sensitive data. The route itself is preserved.
    """
    await get_owned_route_or_404(admin, route_id, current_user.id, columns="id")

    await execute_query(admin.table("webhook_logs").delete().eq("route_id", route_id))


# ---------------------------------------------------------------------------
# Route analytics
# ---------------------------------------------------------------------------
@router.get(
    "/routes/{route_id}/stats",
    response_model=RouteStatsResponse,
)
async def get_route_stats(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Get aggregated delivery statistics for a route.

    Uses a single SQL aggregation query for performance, avoiding loading
    all log rows into application memory.
    """
    await get_owned_route_or_404(admin, route_id, current_user.id, columns="id")

    stats = (
        await execute_query(admin.rpc("get_route_stats", {"p_route_id": route_id}))
    ).data

    if not stats:
        return RouteStatsResponse(route_id=route_id)

    row = stats[0]
    total = row.get("total_deliveries", 0) or 0
    successful = row.get("successful_deliveries", 0) or 0
    success_rate = round((successful / total) * 100, 1) if total > 0 else 0.0

    return RouteStatsResponse(
        route_id=route_id,
        total_deliveries=total,
        successful_deliveries=successful,
        failed_deliveries=row.get("failed_deliveries", 0) or 0,
        timeout_count=row.get("timeout_count", 0) or 0,
        avg_latency_ms=row.get("avg_latency_ms"),
        deliveries_24h=row.get("deliveries_24h", 0) or 0,
        deliveries_7d=row.get("deliveries_7d", 0) or 0,
        deliveries_30d=row.get("deliveries_30d", 0) or 0,
        success_rate_percent=success_rate,
    )


@router.get(
    "/routes/{route_id}/failures",
    response_model=WebhookFailuresResponse,
)
async def list_route_failures(
    route_id: str,
    cursor: Optional[str] = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """List exhausted webhook delivery failures for a route.

    Uses cursor-based pagination with ``created_at`` timestamps for stable
    descending-chronological paging.

    Args:
        route_id: The route UUID.
        cursor: Optional pagination cursor (ISO 8601 ``created_at`` timestamp
            of the last item from the previous page).
        limit: Maximum number of failures to return.
        current_user: Injected authenticated user.

    Returns:
        A :class:`WebhookFailuresResponse` with failures and next cursor.

    Raises:
        HTTPException: 404 if the route does not exist or belongs to another user.
    """
    await get_owned_route_or_404(admin, route_id, current_user.id, columns="id")

    query = (
        admin.table("webhook_failures")
        .select("*")
        .eq("route_id", route_id)
        .order("created_at", desc=True)
        .limit(limit + 1)
    )

    if cursor:
        # Results are ordered newest-first (desc). The cursor is the
        # ``created_at`` of the last item returned on the previous page, so the
        # next page must fetch items *strictly older* than the cursor. Using
        # ``<=`` would re-include (and duplicate) that boundary row.
        query = query.lt("created_at", cursor)

    result = await execute_query(query)

    failures = result.data or []
    has_next = len(failures) > limit
    if has_next:
        failures = failures[:limit]

    next_cursor = failures[-1]["created_at"] if has_next and failures else None

    return WebhookFailuresResponse(
        route_id=route_id,
        failures=[
            WebhookFailureResponse(
                id=f["id"],
                route_id=f["route_id"],
                status_code=f.get("status_code"),
                error_message=f.get("error_message"),
                retry_count=f.get("retry_count", 0),
                max_retries=f.get("max_retries", 3),
                created_at=f["created_at"],
                updated_at=f["updated_at"],
            )
            for f in failures
        ],
        next_cursor=next_cursor,
    )


@router.post("/routes/{route_id}/failures/{log_id}/retry")
async def retry_failed_webhook(
    route_id: str,
    log_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Manually retry a failed webhook delivery.

    Moves the webhook log entry from `exhausted` back to `pending` so the
    next cron run will pick it up. This is useful for operators who want to
    force a retry without waiting for the scheduled job.

    Args:
        route_id: The route UUID.
        log_id: The webhook log entry ID to retry.
        current_user: Injected authenticated user.

    Returns:
        JSON confirmation of the retry request.

    Raises:
        HTTPException: 404 if the route or log entry does not exist.
    """
    await get_owned_route_or_404(admin, route_id, current_user.id, columns="id")

    result = await execute_query(
        admin.table("webhook_logs")
        .select("id, retry_status")
        .eq("id", log_id)
        .eq("route_id", route_id)
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook log not found",
        )

    log_entry = result.data[0]
    if log_entry["retry_status"] != "exhausted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only exhausted deliveries can be manually retried",
        )

    await execute_query(
        admin.table("webhook_logs")
        .update(
            {
                "retry_status": "pending",
                "next_retry_at": datetime.now(timezone.utc).isoformat(),
                "retry_count": 0,
            }
        )
        .eq("id", log_id)
    )

    return RetryQueuedResponse(status="queued", log_id=int(log_id))


@router.post("/routes/{route_id}/logs/{log_id}/replay")
async def replay_webhook_log(
    route_id: str,
    log_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Manually replay a webhook delivery from a log entry.

    Retrieves the stored request body from the webhook log and re-forwards
    it to the route's destination URL. Useful for testing or recovering from
    downstream failures without requiring the original client to resend.

    Args:
        route_id: The route UUID.
        log_id: The webhook log entry ID to replay.
        current_user: Injected authenticated user.

    Returns:
        JSON with ``status`` and ``destination_status``.

    Raises:
        HTTPException: 404 if the route or log entry does not exist.
        HTTPException: 400 if the log entry has no stored request body.
    """
    await get_owned_route_or_404(admin, route_id, current_user.id, columns="*")

    result = await execute_query(
        admin.table("webhook_logs")
        .select("*")
        .eq("id", log_id)
        .eq("route_id", route_id)
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook log not found",
        )

    log_entry = result.data[0]
    route = await route_repository.find_by_id(route_id, current_user.id)
    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found",
        )

    try:
        forward_body = rebuild_retry_body(log_entry)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not forward_body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No request body available for replay",
        )

    method = route.get("method", "POST")
    destination = route["destination_url"]
    headers = route.get("headers", {})
    content_type = log_entry.get("content_type", "")
    if content_type and not any(
        key.lower() == "content-type" for key in headers
    ):
        headers["Content-Type"] = content_type

    status_code, response_body, response_headers = await forward_payload(
        method=method,
        url=destination,
        body=forward_body,
        headers=headers,
    )

    await log_delivery(
        route_id=route_id,
        status_code=status_code,
        payload=log_entry.get("request_body") or {},
        response_body=response_body,
        response_headers=response_headers,
        client_ip=log_entry.get("ip_address", "0.0.0.0"),
        user_agent=log_entry.get("user_agent"),
        duration_ms=0,
        content_type=content_type,
        idempotency_key=None,
        retry_status="none",
        next_retry_at=None,
    )

    return JSONResponse(
        content={
            "status": "replayed",
            "destination_status": status_code,
        }
    )
