from fastapi import APIRouter, HTTPException, Depends, Header, status
from pydantic import BaseModel, Field, ConfigDict

from app.config import settings
from app.database import admin, verify_api_key, generate_api_key
from app.models import (
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    ApiKeyRotateRequest,
    RouteCreateResponse,
    User,
    Token,
)

router = APIRouter(prefix="/auth", tags=["Authentication & Routes"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class AuthCredentials(BaseModel):
    """Login / registration credentials (deprecated)."""

    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    email: str = Field(..., pattern="^[^@]+@[^@]+\\.[^@]+$")
    password: str = Field(..., min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# Helpers
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

    token = authorization.split(" ", 1)[1]

    try:
        # Validate JWT locally using Supabase JWKS.
        import jwt
        from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
        import httpx

        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/jwks"
        async with httpx.AsyncClient() as client:
            jwks_response = await client.get(jwks_url)
            jwks_data = jwks_response.json()

        # Find the key matching the token's kid.
        unverified_header = jwt.get_unverified_header(token)
        key_id = unverified_header.get("kid")
        public_key = None
        for key in jwks_data.get("keys", []):
            if key.get("kid") == key_id:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break

        if not public_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: signing key not found",
            )

        # Verify and decode the JWT.
        payload = jwt.decode(
            token,
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

        # Fetch full user profile from Supabase Auth.
        user_result = await admin.auth.admin.get_user_by_id(user_id)
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
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )
    except Exception:
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

    # Fetch the user profile.
    user_result = await admin.auth.admin.get_user_by_id(user_id)
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


# ---------------------------------------------------------------------------
# Deprecated email/password auth
# ---------------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_410_GONE)
async def register_user(credentials: AuthCredentials):
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
async def login_user(credentials: AuthCredentials):
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
@router.post("/routes", response_model=RouteCreateResponse, status_code=status.HTTP_201_CREATED)
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
    slug_base = route_data.name.lower().replace(" ", "-")
    slug = f"{slug_base}-{current_user.id[:8]}"

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
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A route with this name already exists",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create route: {str(e)}",
        )


@router.get("/routes", response_model=list[RouteResponse])
async def list_routes(current_user: User = Depends(get_current_user_from_jwt)):
    """List all routes owned by the authenticated user.

    Args:
        current_user: Injected authenticated user.

    Returns:
        A list of :class:`RouteResponse` ordered by creation date.
    """
    result = (
        admin.table("routes")
        .select("*")
        .eq("user_id", current_user.id)
        .order("created_at", desc=False)
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
    fields remain unchanged.

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
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Slug already in use",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update route: {str(e)}",
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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rotate API key: {str(e)}",
        )
