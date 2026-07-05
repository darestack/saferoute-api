"""Tests for Pydantic models (input validation and serialization)."""

import pytest
from pydantic import ValidationError

from app.models import (
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    RouteStatsResponse,
    UserCreate,
    WebhookLogResponse,
)


class TestRouteCreate:
    """Validation tests for RouteCreate schema."""

    def test_valid_minimal(self):
        route = RouteCreate(
            name="My Route",
            destination_url="https://hooks.example.com/webhook",
        )
        assert route.name == "My Route"
        assert route.method == "POST"
        assert route.rate_limit == 30
        assert route.webhook_secret is None

    def test_valid_full(self):
        route = RouteCreate(
            name="Full Route",
            destination_url="https://hooks.example.com/webhook",
            method="PUT",
            headers={"X-Custom": "value"},
            webhook_secret="my_secret_key_12345",
            rate_limit=100,
            transform_headers={"X-Injected": "true"},
            transform_body_template='{"email": "{{data.customer.email}}"}',
        )
        assert route.method == "PUT"
        assert route.rate_limit == 100
        assert route.webhook_secret == "my_secret_key_12345"

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError):
            RouteCreate(
                name="",
                destination_url="https://hooks.example.com/webhook",
            )

    def test_rejects_http_url(self):
        with pytest.raises(ValidationError):
            RouteCreate(
                name="Insecure",
                destination_url="http://insecure.example.com/webhook",
            )

    def test_rejects_invalid_method(self):
        with pytest.raises(ValidationError):
            RouteCreate(
                name="Bad Method",
                destination_url="https://hooks.example.com/webhook",
                method="INVALID",
            )

    def test_rejects_rate_limit_zero(self):
        with pytest.raises(ValidationError):
            RouteCreate(
                name="No Rate",
                destination_url="https://hooks.example.com/webhook",
                rate_limit=0,
            )

    def test_rejects_rate_limit_over_max(self):
        with pytest.raises(ValidationError):
            RouteCreate(
                name="Too High",
                destination_url="https://hooks.example.com/webhook",
                rate_limit=1001,
            )

    def test_rejects_short_webhook_secret(self):
        with pytest.raises(ValidationError):
            RouteCreate(
                name="Short Secret",
                destination_url="https://hooks.example.com/webhook",
                webhook_secret="short",
            )


class TestRouteUpdate:
    """Validation tests for RouteUpdate schema."""

    def test_all_optional(self):
        update = RouteUpdate()
        dumped = update.model_dump(exclude_none=True)
        assert dumped == {}

    def test_partial_update(self):
        update = RouteUpdate(name="New Name", rate_limit=50)
        dumped = update.model_dump(exclude_none=True)
        assert dumped == {"name": "New Name", "rate_limit": 50}


class TestRouteResponse:
    """Tests for RouteResponse serialization."""

    def test_from_db_row(self, sample_route):
        response = RouteResponse(
            **sample_route,
            has_webhook_secret=False,
            has_transform=False,
        )
        assert response.id == "route-uuid-1234"
        assert response.rate_limit == 30
        assert response.has_webhook_secret is False
        assert response.transform_headers == {}
        assert response.transform_body_template is None

    def test_exposes_transform_fields(self, sample_route):
        sample_route["transform_headers"] = {"X-Injected": "true"}
        sample_route["transform_body_template"] = '{"email": "{{data.customer.email}}"}'
        response = RouteResponse(
            **sample_route,
            has_webhook_secret=False,
            has_transform=True,
        )
        assert response.transform_headers == {"X-Injected": "true"}
        assert response.transform_body_template == '{"email": "{{data.customer.email}}"}'


class TestUserCreate:
    """Validation tests for UserCreate schema."""

    def test_valid(self):
        user = UserCreate(
            email="test@example.com",
            password="securepassword123",
        )
        assert user.email == "test@example.com"

    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            UserCreate(email="not-an-email", password="securepassword123")

    def test_rejects_short_password(self):
        with pytest.raises(ValidationError):
            UserCreate(email="test@example.com", password="short")


class TestRouteStatsResponse:
    """Tests for RouteStatsResponse defaults."""

    def test_defaults(self):
        stats = RouteStatsResponse(route_id="test-id")
        assert stats.total_deliveries == 0
        assert stats.success_rate_percent == 0.0
        assert stats.avg_latency_ms is None


class TestWebhookLogResponse:
    """Tests for WebhookLogResponse serialization."""

    def test_minimal(self):
        log = WebhookLogResponse(
            id=1,
            route_id="route-uuid",
            created_at="2026-01-01T00:00:00Z",
        )
        assert log.retry_count == 0
        assert log.retry_status == "none"
