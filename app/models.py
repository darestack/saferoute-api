"""Pydantic validation schemas for SafeRoute API.

Contains request and response models for route management, webhook logs,
authentication, and route configuration. All schemas enforce strict typing
and input constraints consistent with the Supabase tables defined in
``schema.sql``.
"""

from typing import Optional, Annotated

from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Shared constrained types
# ---------------------------------------------------------------------------
Slug = Annotated[str, Field(pattern="^[a-z0-9-]+$", max_length=50)]
"""Public route identifier. Lowercase alphanumeric and hyphens only."""

HttpsUrl = Annotated[
    str,
    Field(
        pattern="^https://",
        examples=["https://hooks.zapier.com/hooks/catch/..."],
    ),
]
"""URL constrained to HTTPS to prevent MITM forwarding."""


# ---------------------------------------------------------------------------
# Route models
# ---------------------------------------------------------------------------
class RouteCreate(BaseModel):
    """Schema for creating a new proxy route.

    Attributes:
        name: Human-readable label for the route.
        destination_url: The HTTPS endpoint to forward webhooks to.
        method: HTTP method used when forwarding.
        headers: Optional extra headers to attach to the forwarded request.
    """

    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100)
    destination_url: HttpsUrl
    method: str = Field(default="POST", pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    headers: dict[str, str] = Field(default_factory=dict)


class RouteResponse(BaseModel):
    """Schema returned when reading a route from the API.

    Attributes:
        id: Internal UUID of the route.
        user_id: Owner of the route (matches ``auth.users.id``).
        name: Human-readable label.
        slug: Public identifier used in the proxy URL path.
        destination_url: The hidden destination webhook URL.
        method: HTTP method used for forwarding.
        headers: Extra headers attached to forwarded requests.
        is_active: Whether the route accepts traffic.
        requests_count: Total forwarded requests.
        last_used_at: ISO 8601 timestamp of the most recent request.
        api_key_prefix: First 8 characters of the API key for identification.
        created_at: ISO 8601 timestamp of creation.
        updated_at: ISO 8601 timestamp of last modification.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    slug: Slug
    destination_url: HttpsUrl
    method: str
    headers: dict[str, str]
    is_active: bool
    requests_count: int
    last_used_at: Optional[str] = None
    api_key_prefix: Optional[str] = None
    created_at: str
    updated_at: str


class RouteCreateResponse(RouteResponse):
    """Schema returned after creating a route, includes the full API key.

    Attributes:
        api_key: The full API key. Shown only once at creation time.
            Store it securely; it cannot be retrieved again.
    """

    api_key: str


class RouteUpdate(BaseModel):
    """Schema for updating an existing route. All fields are optional."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    destination_url: Optional[HttpsUrl] = None
    method: Optional[str] = Field(None, pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    headers: Optional[dict[str, str]] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Webhook log models
# ---------------------------------------------------------------------------
class WebhookLogResponse(BaseModel):
    """Schema for a single webhook delivery log entry.

    Attributes:
        id: Auto-incremented log entry ID.
        route_id: The route this log belongs to.
        status_code: HTTP status returned by the destination.
        duration_ms: Time spent processing the request in milliseconds.
        error_message: Error text if forwarding failed.
        created_at: ISO 8601 timestamp of the delivery attempt.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    route_id: str
    status_code: Optional[int] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    created_at: str


# ---------------------------------------------------------------------------
# Auth models
# ---------------------------------------------------------------------------
class User(BaseModel):
    """Public user profile returned by the API.

    Attributes:
        id: Supabase Auth user ID (UUID).
        email: User email address.
        full_name: Optional display name.
        created_at: ISO 8601 timestamp of account creation.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: Optional[str] = None
    created_at: str


class UserCreate(BaseModel):
    """Schema for registering a new user.

    Attributes:
        email: User email address.
        password: Account password. Minimum 8 characters.
        full_name: Optional display name.
    """

    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    email: str = Field(..., pattern="^[^@]+@[^@]+\\.[^@]+$")
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=100)


class Token(BaseModel):
    """OAuth2-compatible token response.

    Attributes:
        access_token: The JWT access token.
        token_type: Token type, always ``"bearer"``.
    """

    access_token: str
    token_type: str = "bearer"


class ApiKeyRotateRequest(BaseModel):
    """Schema for rotating a route's API key."""

    route_id: str