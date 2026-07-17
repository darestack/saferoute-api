"""Pydantic validation schemas for SafeRoute API.

Contains request and response models for route management, webhook logs,
authentication, and route configuration. All schemas enforce strict typing
and input constraints consistent with the Supabase tables defined in
``schema.sql``.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Optional, Annotated

from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Shared constrained types
# ---------------------------------------------------------------------------
Slug = Annotated[str, Field(pattern="^[a-z0-9-]+$", min_length=1, max_length=64)]
"""Public route identifier. Lowercase alphanumeric and hyphens only."""

from pydantic import HttpUrl  # noqa: E402
from pydantic.functional_validators import AfterValidator  # noqa: E402


def _require_https(v: HttpUrl) -> str:
    if v.scheme != "https":
        raise ValueError("URL scheme must be https")
    return str(v)


HttpsUrl = Annotated[
    HttpUrl,
    AfterValidator(_require_https),
]
"""URL constrained to HTTPS using robust Pydantic parsing."""


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
    webhook_secrets: Optional[list[str]] = Field(None, max_length=10)
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
    last_used_at: Optional[datetime] = None
    api_key_prefix: Optional[str] = None
    rate_limit: int = 30
    has_webhook_secret: bool = False
    has_transform: bool = False
    transform_headers: dict[str, str] = Field(default_factory=dict)
    transform_body_template: Optional[str] = None
    form_schema: dict[str, Any] = Field(default_factory=dict)
    spam_honeypot_field: Optional[str] = None
    spam_blocked_ua: list[str] = Field(default_factory=list)
    spam_allowed_countries: list[str] = Field(default_factory=list)
    spam_blocked_ips: list[str] = Field(default_factory=list)
    turnstile_enabled: bool = False
    turnstile_site_key: Optional[str] = None
    turnstile_secret_key: Optional[str] = None
    email_notifications: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


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
    webhook_secrets: Optional[list[str]] = Field(None, max_length=10)
    clear_webhook_secret: Optional[bool] = None
    rate_limit: Optional[int] = Field(None, ge=1, le=1000)
    transform_headers: Optional[dict[str, str]] = None
    transform_body_template: Optional[str] = Field(None, max_length=10000)
    form_schema: Optional[dict[str, Any]] = None
    spam_honeypot_field: Optional[str] = None
    spam_blocked_ua: Optional[list[str]] = None
    spam_allowed_countries: Optional[list[str]] = None
    spam_blocked_ips: Optional[list[str]] = None
    turnstile_enabled: Optional[bool] = None
    turnstile_site_key: Optional[str] = None
    turnstile_secret_key: Optional[str] = None
    email_notifications: Optional[dict[str, Any]] = None


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
    created_at: datetime
    updated_at: datetime


class WebhookFailureResponse(BaseModel):
    """Schema for a webhook failure entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    route_id: str
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime
    updated_at: datetime


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


class OutboundHealthResponse(BaseModel):
    """Outbound connectivity health check response."""

    status: str
    target: str
    status_code: Optional[int] = None
    duration_ms: int
    error: Optional[str] = None


class RetryQueuedResponse(BaseModel):
    """Response when a webhook delivery is queued for retry."""

    status: str
    log_id: int


class RetryProcessResponse(BaseModel):
    """Response from the process-retries endpoint."""

    processed: int
    results: list[dict[str, Any]]


class CleanupResponse(BaseModel):
    """Response from the cleanup endpoint."""

    webhook_logs_removed: int
    rate_limits_cleaned: bool
    pkce_verifiers_cleaned: bool
    idempotency_cache_cleaned: bool
    keep_days: int


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
        credits: Remaining credit balance.
        tier: User pricing tier (free/starter/builder/agency).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: Optional[str] = None
    created_at: Optional[datetime] = None
    credits: int = 0
    tier: str = "free"


class UserCreate(BaseModel):
    """Schema for registering a new user.

    Attributes:
        email: User email address.
        password: Account password. Minimum 8 characters.
        full_name: Optional display name.
    """

    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
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


# ---------------------------------------------------------------------------
# Payment models
# ---------------------------------------------------------------------------
class PaymentInitializeRequest(BaseModel):
    """Schema for initializing a credit pack purchase.

    Attributes:
        tier: The pricing tier (starter/builder/agency).
        email: Customer email for Paystack receipt.
    """

    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    tier: str = Field(..., pattern="^(starter|builder|agency)$")
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PaymentInitializeResponse(BaseModel):
    """Schema returned after initializing a payment.

    Attributes:
        authorization_url: Paystack checkout URL.
        reference: Unique transaction reference.
        amount: Amount in kobo (NGN).
        currency: Currency code for Paystack (always ``"NGN"``).
        usd_amount: Original USD amount.
        display_currency: User's preferred currency.
    """

    authorization_url: str
    reference: str
    amount: int
    currency: str = "NGN"
    usd_amount: Optional[float] = None
    display_currency: str = "USD"


class PaymentVerifyResponse(BaseModel):
    """Schema returned after verifying a payment.

    Attributes:
        status: Transaction status.
        reference: Transaction reference.
        amount: Amount paid in kobo.
        credits_added: Credits added to user account.
        new_balance: New credit balance after top-up.
    """

    status: str
    reference: str
    amount: int
    credits_added: int
    new_balance: int


class PaymentTransactionResponse(BaseModel):
    """Schema for a payment transaction record.

    Attributes:
        id: Transaction UUID.
        reference: Paystack transaction reference.
        amount: Amount in kobo.
        currency: Currency code.
        tier: Purchased tier.
        credits_to_add: Credits that were/are to be added.
        status: Transaction status.
        created_at: ISO 8601 timestamp.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    reference: str
    amount: int
    currency: str
    tier: str
    credits_to_add: int
    status: str
    created_at: datetime
