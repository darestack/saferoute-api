"""Pydantic validation schemas for SafeRoute API.

Contains request and response models for route management, webhook logs,
authentication, and route configuration. All schemas enforce strict typing
and input constraints consistent with the Supabase tables defined in
``schema.sql``.
"""

from __future__ import annotations
from typing import Optional, Annotated

from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Shared constrained types
# ---------------------------------------------------------------------------
Slug = Annotated[str, Field(pattern="^[a-z0-9-]+$", min_length=1, max_length=64)]
"""Public route identifier. Lowercase alphanumeric and hyphens only."""

HttpsUrl = Annotated[
    str,
    Field(
        pattern="^https://[^/]",
        examples=["https://hooks.zapier.com/hooks/catch/..."],
    ),
]
"""URL constrained to HTTPS with a non-empty hostname."""


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
        webhook_secret: Optional shared secret for HMAC signature
            verification on inbound webhooks.
        rate_limit: Maximum requests per minute per IP. Defaults to 30.
        transform_headers: Extra headers to inject into the outbound
            request when forwarding.
        transform_body_template: Optional template string with
            ``{{field.path}}`` placeholders for payload transformation.
    """

    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100)
    destination_url: HttpsUrl
    method: str = Field(default="POST", pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    headers: dict[str, str] = Field(default_factory=dict)
    webhook_secret: Optional[str] = Field(None, min_length=8, max_length=256)
    rate_limit: int = Field(default=30, ge=1, le=1000)
    transform_headers: dict[str, str] = Field(default_factory=dict)
    transform_body_template: Optional[str] = Field(None, max_length=10000)


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
        api_key_prefix: First 12 characters of the API key for identification.
        rate_limit: Per-IP rate limit (requests per minute).
        has_webhook_secret: Whether the route has signature verification.
        has_transform: Whether the route has payload transformation.
        transform_headers: Extra headers to inject into the outbound request.
        transform_body_template: Optional template string for payload transformation.
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
    rate_limit: int = 30
    has_webhook_secret: bool = False
    has_transform: bool = False
    transform_headers: dict[str, str] = Field(default_factory=dict)
    transform_body_template: Optional[str] = None
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
    webhook_secret: Optional[str] = Field(None, min_length=8, max_length=256)
    clear_webhook_secret: Optional[bool] = None
    rate_limit: Optional[int] = Field(None, ge=1, le=1000)
    transform_headers: Optional[dict[str, str]] = None
    transform_body_template: Optional[str] = Field(None, max_length=10000)


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
        retry_count: Number of retry attempts made.
        retry_status: Current retry state (none/pending/retrying/exhausted/succeeded).
        created_at: ISO 8601 timestamp of the delivery attempt.
        updated_at: ISO 8601 timestamp of the last modification.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    route_id: str
    status_code: Optional[int] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    retry_status: str = "none"
    created_at: str
    updated_at: str


class WebhookFailureResponse(BaseModel):
    """Schema for a webhook failure entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    route_id: str
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: str
    updated_at: str


class WebhookFailuresResponse(BaseModel):
    """Paginated list of webhook failures for a route."""

    route_id: str
    failures: list[WebhookFailureResponse]
    next_cursor: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    database: str
    service: str


class RouteStatsResponse(BaseModel):
    """Aggregated delivery statistics for a route.

    Attributes:
        route_id: The route these stats belong to.
        total_deliveries: Total number of delivery attempts.
        successful_deliveries: Count of 2xx responses.
        failed_deliveries: Count of 4xx/5xx responses.
        timeout_count: Count of 504 (timeout) responses.
        avg_latency_ms: Average delivery latency in milliseconds.
        deliveries_24h: Deliveries in the last 24 hours.
        deliveries_7d: Deliveries in the last 7 days.
        deliveries_30d: Deliveries in the last 30 days.
        success_rate_percent: Percentage of successful deliveries.
    """

    model_config = ConfigDict(from_attributes=True)

    route_id: str
    total_deliveries: int = 0
    successful_deliveries: int = 0
    failed_deliveries: int = 0
    timeout_count: int = 0
    avg_latency_ms: Optional[float] = None
    deliveries_24h: int = 0
    deliveries_7d: int = 0
    deliveries_30d: int = 0
    success_rate_percent: float = 0.0


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
    created_at: Optional[str] = None


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
