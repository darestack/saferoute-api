"""Authentication and route management endpoints.

Provides JWT-based authentication, route CRUD, API key rotation, and
webhook log retrieval.
"""

import asyncio
import inspect
import logging
import secrets
import time
from typing import Optional

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, ConfigDict

from app.config import settings
from app.database import admin, verify_api_key, generate_api_key
from app.models import (
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    RouteCreateResponse,
    RouteStats,
    User,
    UserCreate,
    Token,
    WebhookLogResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication & Routes"])

# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------
_JWKS_CACHE_TTL_SECONDS = 300  # 5 minutes
_jwks_cache: Optional[dict] = None
_jwks_cache_expiry: float = 0.0
_jwks_lock = asyncio.Lock()


async def _get_cached_jwks() -> dict:
    """Fetch Supabase JWKS, using a TTL-based cache to avoid fetching on
    every authenticated request.

    Returns:
        The parsed JWKS response dict.

    Raises:
        HTTPException: 401 if the JWKS endpoint is unreachable.
    """
    global _jwks_cache, _jwks_cache_expiry

    now = time.monotonic()
    if _jwks_cache is not None and now < _jwks_cache_expiry:
        return _jwks_cache

    async with _jwks_lock:
        # Re-check after acquiring lock (another coroutine may have refreshed).
        now = time.monotonic()
        if _jwks_cache is not None and now < _jwks_cache_expiry:
            return _jwks_cache

        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/jwks"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(jwks_url, timeout=5.0)
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
# Auth helpers
# ---------------------------------------------------------------------------
async def get_current_user_from_jwt(
    authorization: Optional[str] = Header(None),
) -> User:
    """Return the current authenticated user from a JWT Bearer token.

    Validates the token locally using PyJWT and Supabase JWKS, then fetches
    the user profile from Supabase Auth using the service-role client.

    Args:
        authorization: ``Authorization: Bearer <token>`` header.

    Returns:
        The authenticated :class:`User`.

    Raises:
        HTTPException: 401 if the token is missing, invalid, or expired.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )

    token_str = authorization.split(" ", 1)[1]

    try:
        jwks = await _get_cached_jwks()

        unverified_header = jwt.get_unverified_header(token_str)
        key_id = unverified_header.get("kid")
        public_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == key_id:
                public_key = RSAAlgorithm.from_jwk(key)
                break

        if not public_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: signing key not found",
            )

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

        # Handle both sync and async Supabase clients gracefully.
        result = admin.auth.admin.get_user_by_id(user_id)
        if inspect.isawaitable(result):
            result = await result

        user_result = result
        if not user_result.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        return User(
            id=user_result.user.id,
            email=user_result.user.email or email or "",
            full_name=getattr(user_result.user, "full_name", None),
            created_at=user_result.user.created_at,
        )

    except HTTPException:
        raise
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
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
    """Return the route owner and route ID from a valid API key.

    Args:
        x_api_key: ``X-API-Key: sk_live_xxx`` header.

    Returns:
        A tuple of ``(route_owner_user, route_id)``.

    Raises:
        HTTPException: 401 if the API key is missing or invalid.
    """
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

    route_result = (
        admin.table("routes").select("user_id").eq("id", route_id).execute()
    )

    if not route_result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Route not found for API key",
        )

    user_id = route_result.data[0]["user_id"]

    # Fetch the user profile (handle sync/async).
    result = admin.auth.admin.get_user_by_id(user_id)
    if inspect.isawaitable(result):
        result = await result

    user_result = result
    if not user_result.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for API key",
        )

    user = User(
        id=user_result.user.id,
        email=user_result.user.email,
        full_name=getattr(user_result.user, "full_name", None),
        created_at=user_result.user.created_at,
    )

    return user, route_id


def _generate_slug(name: str, user_id: str) -> str:
    """Generate a collision-safe slug from a route name.

    Appends a random 6-character hex suffix to prevent collisions when
    a user recreates a route with the same name or when two users share
    the same user-ID prefix.

    Args:
        name: The human-readable route name.
        user_id: The owner's user ID.

    Returns:
        A slug string like ``my-route-a3f9b1``.
    """
    slug_base = name.lower().replace(" ", "-")
    random_suffix = secrets.token_hex(3)
    return f"{slug_base}-{random_suffix}"


def _safe_error_detail(exc: Exception) -> str:
    """Return a safe error detail string.

    In development, includes the full exception message.
    In production, returns a generic message to avoid leaking internals.

    Args:
        exc: The caught exception.

    Returns:
        A user-safe error detail string.
    """
    if settings.ENVIRONMENT == "development":
        return str(exc)
    return "An internal error occurred"


# ---------------------------------------------------------------------------
# Deprecated email/password auth
# ---------------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_410_GONE)
async def register_user(credentials: UserCreate):
    """Register a new user with email and password.

    .. deprecated::
        Email/password registration is deprecated. Use OAuth instead.

    Returns:
        410 Gone with instructions to use OAuth.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Email/password registration is deprecated. "
              "Use /auth/oauth/google or /auth/oauth/github instead.",
    )


@router.post("/login", status_code=status.HTTP_410_GONE)
async def login_user(credentials: UserCreate):
    """Login with email and password.

    .. deprecated::
        Email/password login is deprecated. Use OAuth instead.

    Returns:
        410 Gone with instructions to use OAuth.
    """
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
    """Return the currently authenticated user's profile.

    Returns:
        The :class:`User` profile for the caller.
    """
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

    Generates a public ``slug`` from the route name and a unique API key
    for programmatic route management. The full API key is returned only
    once — store it securely.

    Args:
        route_data: Route configuration (name, destination URL, method).
        current_user: Injected authenticated user.

    Returns:
        The created :class:`RouteCreateResponse` including the API key.

    Raises:
        HTTPException: 409 if a route with the same name already exists.
        HTTPException: 500 if database insertion fails.
    """
    slug = _generate_slug(route_data.name, current_user.id)
    full_key, key_prefix, key_hash = generate_api_key()

    try:
        result = admin.table("routes").insert(
            {
                "user_id": current_user.id,
                "name": route_data.name,
                "slug": slug,
                "destination_url": str(route_data.destination_url),
                "method": route_data.method,
                "headers": route_data.headers,
                "api_key_prefix": key_prefix,
                "api_key_hash": key_hash,
            }
        ).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create route",
            )

        route = result.data[0]
        return RouteCreateResponse(
            id=route["id"],
            user_id=route["user_id"],
            name=route["name"],
            slug=route["slug"],
            destination_url=route["destination_url"],
            method=route["method"],
            headers=route["headers"],
            is_active=route["is_active"],
            requests_count=route["requests_count"],
            last_used_at=route.get("last_used_at"),
            api_key_prefix=route.get("api_key_prefix"),
            created_at=route["created_at"],
            updated_at=route["updated_at"],
            api_key=full_key,
        )
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
            detail=_safe_error_detail(exc),
        )


@router.get("/routes", response_model=list[RouteResponse])
async def list_routes(
    current_user: User = Depends(get_current_user_from_jwt),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List all routes owned by the authenticated user.

    Supports pagination via ``limit`` and ``offset`` query parameters.

    Args:
        current_user: Injected authenticated user.
        limit: Maximum number of routes to return (1–100, default 20).
        offset: Number of routes to skip (default 0).

    Returns:
        A list of :class:`RouteResponse` ordered by creation date.
    """
    result = (
        admin.table("routes")
        .select("*")
        .eq("user_id", current_user.id)
        .order("created_at", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return [RouteResponse(**row) for row in result.data]


@router.get("/routes/{route_id}", response_model=RouteResponse)
async def get_route(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Retrieve a single route by its internal UUID.

    Args:
        route_id: The UUID of the route.
        current_user: Injected authenticated user.

    Returns:
        The matching :class:`RouteResponse`.

    Raises:
        HTTPException: 404 if the route does not exist or belongs to another user.
    """
    result = (
        admin.table("routes")
        .select("*")
        .eq("id", route_id)
        .eq("user_id", current_user.id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found",
        )

    return RouteResponse(**result.data[0])


@router.put("/routes/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: str,
    route_data: RouteUpdate,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Update an existing route's configuration.

    Only the fields provided in the request body are updated. Unspecified
    fields remain unchanged. When the ``name`` is updated, the ``slug``
    is regenerated to stay in sync.

    Args:
        route_id: The UUID of the route to update.
        route_data: Fields to update.
        current_user: Injected authenticated user.

    Returns:
        The updated :class:`RouteResponse`.

    Raises:
        HTTPException: 404 if the route does not exist or belongs to another user.
        HTTPException: 409 if the new slug conflicts with an existing route.
    """
    updates = route_data.model_dump(exclude_none=True)

    if "destination_url" in updates:
        updates["destination_url"] = str(updates["destination_url"])

    # When name changes, regenerate slug to stay in sync.
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

        return RouteResponse(**result.data[0])
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
            detail=_safe_error_detail(exc),
        )


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Delete a route owned by the authenticated user.

    Args:
        route_id: The UUID of the route to delete.
        current_user: Injected authenticated user.

    Raises:
        HTTPException: 404 if the route does not exist or belongs to another user.
    """
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

    return None


@router.post("/routes/{route_id}/rotate-key", response_model=RouteCreateResponse)
async def rotate_api_key(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Rotate the API key for a route.

    Generates a new API key and invalidates the old one. The new key is
    returned only once — store it securely.

    Args:
        route_id: The UUID of the route to rotate the key for.
        current_user: Injected authenticated user.

    Returns:
        The updated :class:`RouteCreateResponse` including the new API key.

    Raises:
        HTTPException: 404 if the route does not exist or belongs to another user.
    """
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
        return RouteCreateResponse(
            id=route["id"],
            user_id=route["user_id"],
            name=route["name"],
            slug=route["slug"],
            destination_url=route["destination_url"],
            method=route["method"],
            headers=route["headers"],
            is_active=route["is_active"],
            requests_count=route["requests_count"],
            last_used_at=route.get("last_used_at"),
            api_key_prefix=route.get("api_key_prefix"),
            created_at=route["created_at"],
            updated_at=route["updated_at"],
            api_key=full_key,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to rotate API key for route %s", route_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_safe_error_detail(exc),
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
    """List webhook delivery logs for a route owned by the authenticated user.

    Returns logs in reverse chronological order (newest first).

    Args:
        route_id: The UUID of the route.
        current_user: Injected authenticated user.
        limit: Maximum number of log entries to return (1–100, default 20).
        offset: Number of entries to skip (default 0).

    Returns:
        A list of :class:`WebhookLogResponse`.

    Raises:
        HTTPException: 404 if the route does not exist or belongs to another user.
    """
    # Verify the route belongs to the current user.
    route_check = (
        admin.table("routes")
        .select("id")
        .eq("id", route_id)
        .eq("user_id", current_user.id)
        .execute()
    )

    if not route_check.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found",
        )

    result = (
        admin.table("webhook_logs")
        .select("*")
        .eq("route_id", route_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return [WebhookLogResponse(**row) for row in result.data]


@router.get(
    "/routes/{route_id}/stats",
    response_model=RouteStats,
)
async def get_route_stats(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Get aggregated delivery statistics for a route.

    Computes success rate, average latency, and request volume from
    ``webhook_logs``.

    Args:
        route_id: The UUID of the route.
        current_user: Injected authenticated user.

    Returns:
        A :class:`RouteStats` object with aggregated metrics.

    Raises:
        HTTPException: 404 if the route does not exist or belongs to another user.
    """
    route_check = (
        admin.table("routes")
        .select("id, requests_count, last_used_at")
        .eq("id", route_id)
        .eq("user_id", current_user.id)
        .execute()
    )

    if not route_check.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found",
        )

    route = route_check.data[0]

    logs_result = (
        admin.table("webhook_logs")
        .select("status_code, duration_ms, created_at")
        .eq("route_id", route_id)
        .execute()
    )

    logs = logs_result.data or []
    total_requests = len(logs)
    success_count = sum(1 for log in logs if log.get("status_code") and 200 <= log["status_code"] < 300)
    error_count = total_requests - success_count
    avg_duration_ms = (
        sum(log["duration_ms"] for log in logs if log.get("duration_ms") is not None) / total_requests
        if total_requests > 0
        else None
    )

    return RouteStats(
        route_id=route_id,
        total_requests=total_requests,
        success_count=success_count,
        error_count=error_count,
        avg_duration_ms=avg_duration_ms,
        last_used_at=route.get("last_used_at"),
    )