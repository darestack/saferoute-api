"""Shared test fixtures and configuration for SafeRoute API tests."""

import os
import sys

# Set required environment variables before importing app modules.
os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("API_KEY_SALT", "test-salt")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("RETRY_ENDPOINT_SECRET", "test-retry-secret")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")
os.environ.setdefault("ENVIRONMENT", "development")

# Ensure project root is on path for imports.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


import pytest


@pytest.fixture
def sample_payload() -> dict:
    """A typical webhook payload for testing."""
    return {
        "event": "order.completed",
        "data": {
            "id": "ord_123",
            "amount": 49.99,
            "customer": {
                "email": "test@example.com",
                "name": "Jane Doe",
            },
            "items": [
                {"sku": "ITEM-001", "quantity": 2},
                {"sku": "ITEM-002", "quantity": 1},
            ],
        },
        "timestamp": "2026-01-15T10:30:00Z",
    }


@pytest.fixture
def sample_route() -> dict:
    """A typical route record from the database."""
    return {
        "id": "route-uuid-1234",
        "user_id": "user-uuid-5678",
        "name": "Test Route",
        "slug": "test-route-a1b2c3",
        "destination_url": "https://hooks.example.com/webhook",
        "method": "POST",
        "headers": {"X-Custom": "value"},
        "is_active": True,
        "requests_count": 42,
        "last_used_at": "2026-01-15T10:30:00Z",
        "api_key_prefix": "sk_live_abc1",
        "api_key_hash": "hashed_value",
        "webhook_secret": None,
        "rate_limit": 30,
        "transform_headers": {},
        "transform_body_template": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-15T10:30:00Z",
    }
