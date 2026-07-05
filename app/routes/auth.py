"""User authentication and route management endpoints.

Provides registration, login, route CRUD, and ``GET /auth/me`` using
Supabase Auth for identity and Supabase tables for route storage.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field, ConfigDict

from app.config import settings
from app.database import supabase_client, admin
from app.models import RouteCreate, RouteResponse, RouteUpdate, User, Token

router = APIRouter(prefix="/auth", tags=["User Authentication"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class AuthCredentials(BaseModel):
    """Login / registration credentials.

    Attributes:
        email: User email address.
        password: Account password. Minimum 8 characters.
    """

    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    email: str = Field(..., pattern="^[^@]+@[^@]+\\.[^@]+$")
    password: str = Field(..., min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> User:
    """Return the current authenticated user from the request headers.

    Args:
        authorization: ``Authorization: Bearer <token>`` header.

    Returns:
        The authenticated :class:`User`.

    Raises:
        HTTPException: 401 if the token is missing or invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.split(" ", 1)[1]

    try:
        result = supabase_client.auth.get_user(token)
        if not result.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return User(
            id=result.user.id,
            email=result.user.email,
            full_name=getattr(result.user, "full_name", None),
            created_at=result.user.created_at,
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
@router.post("/register", response_model=Token)
async def register_user(credentials: AuthCredentials):
    """Register a new user via Supabase Auth.

    Args:
        credentials: Email and password for the new account.

    Returns:
        Access token if registration succeeds.

    Raises:
        HTTPException: 400 with detail from Supabase if registration fails.
    """
    try:
        result = supabase_client.auth.sign_up(
            {
                "email": credentials.email,
                "password": credentials.password,
            }
        )

        if result.session is None:
            error_message = getattr(result, "error", None)
            detail = (
                error_message.message
                if error_message and error_message.message
                else "Registration failed. Check that signups are enabled in Supabase Auth."
            )
            raise HTTPException(status_code=400, detail=detail)

        return Token(
            access_token=result.session.access_token,
            token_type="bearer",
        )
    except HTTPException:
        raise
    except Exception as e:
        detail = "Registration failed. Please try again."
        status_code = 400

        # Preserve rate-limit errors so clients see 429 instead of 400.
        if hasattr(e, "status_code") and e.status_code == 429:
            status_code = 429
            detail = "Too many requests. Please wait a minute and try again."
        elif hasattr(e, "message") and e.message:
            detail = e.message
        elif hasattr(e, "args") and e.args:
            detail = str(e.args[0])

        raise HTTPException(status_code=status_code, detail=detail)


@router.post("/login", response_model=Token)
async def login_user(credentials: AuthCredentials):
    """Authenticate an existing user and return an access token.

    Args:
        credentials: Email and password.

    Returns:
        Access token for subsequent authenticated requests.

    Raises:
        HTTPException: 401 if credentials are invalid, 429 on rate limit.
    """
    try:
        result = supabase_client.auth.sign_in_with_password(
            {
                "email": credentials.email,
                "password": credentials.password,
            }
        )

        if result.session is None:
            error_message = getattr(result, "error", None)
            detail = (
                error_message.message
                if error_message and error_message.message
                else "Invalid email or password."
            )
            raise HTTPException(status_code=401, detail=detail)

        return Token(
            access_token=result.session.access_token,
            token_type="bearer",
        )
    except HTTPException:
        raise
    except Exception as e:
        detail = "Invalid email or password."
        status_code = 401

        if hasattr(e, "status_code") and e.status_code == 429:
            status_code = 429
            detail = "Too many requests. Please wait a minute and try again."
        elif hasattr(e, "message") and e.message:
            detail = e.message
        elif hasattr(e, "args") and e.args:
            detail = str(e.args[0])

        raise HTTPException(status_code=status_code, detail=detail)


@router.get("/me", response_model=User)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile.

    Returns:
        The :class:`User` profile for the caller.
    """
    return current_user


# ---------------------------------------------------------------------------
# Route CRUD
# ---------------------------------------------------------------------------
@router.post("/routes", response_model=RouteResponse)
async def create_route(
    route_data: RouteCreate,
    current_user: User = Depends(get_current_user),
):
    """Create a new proxy route for the authenticated user.

    Args:
        route_data: Route configuration (name, destination URL, method).
        current_user: Injected authenticated user.

    Returns:
        The created :class:`RouteResponse`.

    Raises:
        HTTPException: 409 if a route with the same name already exists.
        HTTPException: 500 if database insertion fails.
    """
    # Generate a unique slug from the name.
    slug_base = route_data.name.lower().replace(" ", "-")
    slug = f"{slug_base}-{current_user.id[:8]}"

    try:
        result = admin.table("routes").insert(
            {
                "user_id": current_user.id,
                "name": route_data.name,
                "slug": slug,
                "destination_url": str(route_data.destination_url),
                "method": route_data.method,
                "headers": route_data.headers,
                "is_active": True,
            }
        ).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to create route")

        return RouteResponse(**result.data[0])
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
            raise HTTPException(status_code=409, detail="A route with this name already exists")
        raise HTTPException(status_code=500, detail="Failed to create route")


@router.get("/routes", response_model=list[RouteResponse])
async def list_routes(current_user: User = Depends(get_current_user)):
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
    current_user: User = Depends(get_current_user),
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
        raise HTTPException(status_code=404, detail="Route not found")

    return RouteResponse(**result.data[0])


@router.put("/routes/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: str,
    route_data: RouteUpdate,
    current_user: User = Depends(get_current_user),
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
        result = (
            admin.table("routes")
            .select("id")
            .eq("slug", updates["slug"])
            .neq("id", route_id)
            .execute()
        )
        if result.data:
            raise HTTPException(status_code=409, detail="Slug already in use")

    try:
        result = (
            admin.table("routes")
            .update(updates)
            .eq("id", route_id)
            .eq("user_id", current_user.id)
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Route not found")

        return RouteResponse(**result.data[0])
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
            raise HTTPException(status_code=409, detail="Slug already in use")
        raise HTTPException(status_code=500, detail="Failed to update route")


@router.delete("/routes/{route_id}")
async def delete_route(
    route_id: str,
    current_user: User = Depends(get_current_user),
):
    """Delete a route owned by the authenticated user.

    Args:
        route_id: The UUID of the route to delete.
        current_user: Injected authenticated user.

    Returns:
        Empty 204 response on success.

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
        raise HTTPException(status_code=404, detail="Route not found")

    return None
