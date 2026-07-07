"""Authentication and route management endpoints.

Provides JWT-based authentication, route CRUD, API key rotation,
webhook log retrieval, and route analytics.
"""

import asyncio
import inspect
import logging
import time
from typing import Optional

import httpx
import jwt
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.config import settings
from app.crypto import encrypt_webhook_secret
from app.database import (
    admin,
    clear_api_key_cache_for_route,
    generate_api_key,
    verify_api_key,
)
from app.models import (
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    RouteCreateResponse,
    RouteStatsResponse,
    User,
    UserCreate,
    WebhookLogResponse,
    WebhookFailureResponse,
    WebhookFailuresResponse,
)
from app.utils.security import (
    generate_slug,
    safe_error_detail,
    validate_destination_url_async,
)
from app.utils.routes import (
    assert_owned_route_exists,
    get_owned_route_or_404,
    route_to_response,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication & Routes"])

# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------
_JWKS_CACHE_TTL_SECONDS = 300
_jwks_cache: Optional[dict] = None
_jwks_cache_expiry: float = 0.0
_jwks_lock = asyncio.Lock()
_jwks_client = httpx.AsyncClient(timeout=5.0)


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

        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/jwks"
        try:
            response = await _jwks_client.get(jwks_url)
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


def _public_key_from_jwks(jwks: dict, key_id: Optional[str], algorithm: str) -> object:
    """Return the public key matching a JWT ``kid`` and signing algorithm."""
    for key in jwks.get("keys", []):
        if key.get("kid") != key_id:
            continue

        key_algorithm = key.get("alg") or algorithm
        if key_algorithm.startswith("ES"):
            return ECAlgorithm.from_jwk(key)
        if key_algorithm.startswith("RS"):
            return RSAAlgorithm.from_jwk(key)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: unsupported signing algorithm",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token: signing key not found",
    )


# ---------------------------------------------------------------------------
# User cache
# ---------------------------------------------------------------------------
_USER_CACHE_TTL_SECONDS = 300
_USER_CACHE_MAX_SIZE = 1000
_user_cache: dict[str, User] = {}
_user_cache_expiry: dict[str, float] = {}
_user_cache_order: list[str] = []
_user_cache_lock = asyncio.Lock()


async def _get_cached_user(user_id: str) -> Optional[User]:
    """Return a cached User if available and fresh."""
    now = time.monotonic()
    expiry = _user_cache_expiry.get(user_id, 0.0)
    if user_id in _user_cache and now < expiry:
        return _user_cache[user_id]
    return None


async def _cache_user(user: User) -> None:
    """Store a User in the cache with TTL and FIFO eviction."""
    async with _user_cache_lock:
        _user_cache[user.id] = user
        _user_cache_expiry[user.id] = time.monotonic() + _USER_CACHE_TTL_SECONDS
        if user.id not in _user_cache_order:
            _user_cache_order.append(user.id)

        # FIFO eviction if over max size.
        while len(_user_cache_order) > _USER_CACHE_MAX_SIZE:
            oldest = _user_cache_order.pop(0)
            _user_cache.pop(oldest, None)
            _user_cache_expiry.pop(oldest, None)


async def _fetch_and_cache_user(user_id: str) -> User:
    """Fetch a user from Supabase Auth and cache the result."""
    cached = await _get_cached_user(user_id)
    if cached:
        return cached

    async with _user_cache_lock:
        # Double-check after acquiring lock.
        now = time.monotonic()
        expiry = _user_cache_expiry.get(user_id, 0.0)
        if user_id in _user_cache and now < expiry:
            return _user_cache[user_id]

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

        # Inline cache write (already holding the lock).
        _user_cache[user.id] = user
        _user_cache_expiry[user.id] = time.monotonic() + _USER_CACHE_TTL_SECONDS
        if user.id not in _user_cache_order:
            _user_cache_order.append(user.id)
        while len(_user_cache_order) > _USER_CACHE_MAX_SIZE:
            oldest = _user_cache_order.pop(0)
            _user_cache.pop(oldest, None)
            _user_cache_expiry.pop(oldest, None)

        return user


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
        algorithm = unverified_header.get("alg", "")
        public_key = _public_key_from_jwks(jwks, key_id, algorithm)

        payload = jwt.decode(
            token_str,
            public_key,
            algorithms=["ES256", "RS256"],
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

        # Prefer JWT claims when cached user data is stale.
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


async def get_current_user_from_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> tuple[User, str]:
    """Return the route owner and route ID from a valid API key."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    route_id = verify_api_key(x_api_key)
    if not route_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    route_result = admin.table("routes").select("user_id").eq("id", route_id).execute()

    if not route_result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Route not found for API key",
        )

    user_id = route_result.data[0]["user_id"]

    user = await _fetch_and_cache_user(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for API key",
        )

    return user, route_id


# ---------------------------------------------------------------------------
# Internal helpers (not exported for reuse)
# ---------------------------------------------------------------------------
def _generate_slug(name: str, user_id: str) -> str:
    """Generate a collision-safe slug from a route name."""
    return generate_slug(name, user_id)


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
    slug = _generate_slug(route_data.name, current_user.id)
    full_key, key_prefix, key_hash = generate_api_key()
    try:
        await validate_destination_url_async(str(route_data.destination_url))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    insert_data = {
        "user_id": current_user.id,
        "name": route_data.name,
        "slug": slug,
        "destination_url": str(route_data.destination_url),
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
    if route_data.transform_body_template:
        insert_data["transform_body_template"] = route_data.transform_body_template

    try:
        result = admin.table("routes").insert(insert_data).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create route",
            )

        route = result.data[0]
        return RouteCreateResponse(**route_to_response(route, api_key=full_key))
    except HTTPException:
        raise
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A route with this name already exists",
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
    result = (
        admin.table("routes")
        .select("*")
        .eq("user_id", current_user.id)
        .order("created_at", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return [RouteResponse(**route_to_response(row)) for row in result.data]


@router.get("/routes/{route_id}", response_model=RouteResponse)
async def get_route(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Retrieve a single route by its internal UUID."""
    route = get_owned_route_or_404(admin, route_id, current_user.id)
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
    existing_route = get_owned_route_or_404(
        admin, route_id, current_user.id, columns="slug"
    )
    old_slug = existing_route["slug"]

    updates = route_data.model_dump(exclude_none=True)

    if "destination_url" in updates:
        updates["destination_url"] = str(updates["destination_url"])
        try:
            await validate_destination_url_async(updates["destination_url"])
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

    if "name" in updates:
        updates["slug"] = _generate_slug(updates["name"], current_user.id)

    if "slug" in updates:
        existing = (
            admin.table("routes")
            .select("id")
            .eq("slug", updates["slug"])
            .neq("id", route_id)
            .execute()
        )
        if existing.data:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Slug already in use",
            )

    if "webhook_secret" in route_data.model_fields_set:
        if route_data.webhook_secret:
            updates["webhook_secret"] = encrypt_webhook_secret(
                route_data.webhook_secret
            )
        else:
            updates["webhook_secret"] = None

    try:
        result = (
            admin.table("routes")
            .update(updates)
            .eq("id", route_id)
            .eq("user_id", current_user.id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Route not found",
            )

        route = result.data[0]
        from app.routes.proxy import clear_route_cache

        clear_route_cache(old_slug)
        clear_route_cache(route["slug"])
        return RouteResponse(**route_to_response(route))
    except HTTPException:
        raise
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
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
    existing_route = get_owned_route_or_404(
        admin, route_id, current_user.id, columns="slug"
    )
    old_slug = existing_route["slug"]

    result = (
        admin.table("routes")
        .delete()
        .eq("id", route_id)
        .eq("user_id", current_user.id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found",
        )

    from app.routes.proxy import clear_route_cache

    clear_route_cache(old_slug)
    return None


@router.post("/routes/{route_id}/rotate-key", response_model=RouteCreateResponse)
async def rotate_api_key(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Rotate the API key for a route. Returns the new key once."""
    full_key, key_prefix, key_hash = generate_api_key()

    try:
        result = (
            admin.table("routes")
            .update(
                {
                    "api_key_prefix": key_prefix,
                    "api_key_hash": key_hash,
                }
            )
            .eq("id", route_id)
            .eq("user_id", current_user.id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Route not found",
            )

        route = result.data[0]
        clear_api_key_cache_for_route(route_id)
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
    assert_owned_route_exists(admin, route_id, current_user.id)

    result = (
        admin.table("webhook_logs")
        .select("*")
        .eq("route_id", route_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return [WebhookLogResponse(**row) for row in result.data]


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
    assert_owned_route_exists(admin, route_id, current_user.id)

    stats = admin.rpc("get_route_stats", {"p_route_id": route_id}).execute().data

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


@router.get("/health")
async def health_check():
    """Check API and database connectivity.

    Returns:
        Health status with database connectivity check.
    """
    db_ok = False
    try:
        # Read-only connectivity probe — no side effects.
        admin.table("routes").select("id").limit(1).execute()
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "service": "SafeRoute API",
    }


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
    assert_owned_route_exists(admin, route_id, current_user.id)

    query = (
        admin.table("webhook_failures")
        .select("*")
        .eq("route_id", route_id)
        .order("created_at", desc=True)
        .limit(limit + 1)
    )

    if cursor:
        query = query.lte("created_at", cursor)

    result = query.execute()

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
            )
            for f in failures
        ],
        next_cursor=next_cursor,
    )
