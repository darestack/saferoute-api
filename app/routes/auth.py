"""Authentication and route management endpoints.

Provides JWT-based authentication, route CRUD, API key rotation,
webhook log retrieval, and route analytics.
"""

import asyncio
import inspect
import logging
import re
import secrets
import time
from typing import Optional

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.config import settings
from app.database import admin, verify_api_key, generate_api_key
from app.models import (
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    RouteCreateResponse,
    RouteStatsResponse,
    User,
    UserCreate,
    WebhookLogResponse,
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
    """Return the current authenticated user from a JWT Bearer token."""
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
            detail=_safe_error_detail(exc),
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

    route_result = (
        admin.table("routes").select("user_id").eq("id", route_id).execute()
    )

    if not route_result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Route not found for API key",
        )

    user_id = route_result.data[0]["user_id"]

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
    """Generate a collision-safe slug from a route name."""
    slug_base = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))
    slug_base = slug_base.strip("-")[:40] or "route"
    random_suffix = secrets.token_hex(3)
    return f"{slug_base}-{random_suffix}"


def _safe_error_detail(exc: Exception) -> str:
    """Return a safe error detail — verbose in dev, generic in prod."""
    if settings.ENVIRONMENT == "development":
        return str(exc)
    return "An internal error occurred"


def _route_to_response(route: dict, api_key: Optional[str] = None) -> dict:
    """Build a RouteResponse-compatible dict from a DB route row.

    Computes ``has_webhook_secret`` and ``has_transform`` from the raw
    data, and strips sensitive fields.

    Args:
        route: The raw route dict from Supabase.
        api_key: If provided, includes the API key (for create/rotate).

    Returns:
        A dict suitable for constructing RouteResponse or RouteCreateResponse.
    """
    response = {
        "id": route["id"],
        "user_id": route["user_id"],
        "name": route["name"],
        "slug": route["slug"],
        "destination_url": route["destination_url"],
        "method": route["method"],
        "headers": route["headers"],
        "is_active": route["is_active"],
        "requests_count": route["requests_count"],
        "last_used_at": route.get("last_used_at"),
        "api_key_prefix": route.get("api_key_prefix"),
        "rate_limit": route.get("rate_limit", 30),
        "has_webhook_secret": bool(route.get("webhook_secret")),
        "has_transform": bool(
            route.get("transform_body_template")
            or route.get("transform_headers")
        ),
        "transform_headers": route.get("transform_headers") or {},
        "transform_body_template": route.get("transform_body_template"),
        "created_at": route["created_at"],
        "updated_at": route["updated_at"],
    }
    if api_key is not None:
        response["api_key"] = api_key
    return response


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
        insert_data["webhook_secret"] = route_data.webhook_secret
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
        return RouteCreateResponse(**_route_to_response(route, api_key=full_key))
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
    """List all routes owned by the authenticated user (paginated)."""
    result = (
        admin.table("routes")
        .select("*")
        .eq("user_id", current_user.id)
        .order("created_at", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return [RouteResponse(**_route_to_response(row)) for row in result.data]


@router.get("/routes/{route_id}", response_model=RouteResponse)
async def get_route(
    route_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Retrieve a single route by its internal UUID."""
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

    return RouteResponse(**_route_to_response(result.data[0]))


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

        return RouteResponse(**_route_to_response(result.data[0]))
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
    """Delete a route owned by the authenticated user."""
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
        return RouteCreateResponse(**_route_to_response(route, api_key=full_key))
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
    """List webhook delivery logs for a route (newest first, paginated)."""
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

    stats = (
        admin.rpc("get_route_stats", {"p_route_id": route_id})
        .execute()
        .data
    )

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