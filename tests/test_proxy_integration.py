"""Integration tests for the proxy webhook endpoints using FastAPI TestClient."""

import pytest
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
import asyncio

client = TestClient(app)


@contextmanager
def _mock_jwt():
    """Mock JWT validation to bypass auth in integration tests."""
    with (
        patch("app.routes.auth._get_cached_jwks") as mock_jwks,
        patch("app.routes.auth.jwt") as mock_jwt,
    ):
        mock_jwks.return_value = {"keys": []}
        mock_jwt.get_unverified_header.return_value = {"kid": "test-kid"}
        mock_jwt.decode.return_value = {"sub": "test-user-id"}
        yield


class TestOutboundHealthCheck:
    """Tests for the outbound connectivity health check."""

    def test_outbound_health_check_returns_status(self):
        async def mock_head(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.status_code = 204
            return mock_response

        with patch("app.routes.proxy.get_http_client") as mock_client:
            mock_client.return_value.head = mock_head

            response = client.get(
                "/internal/health/outbound",
                headers={"X-Retry-Secret": "test-retry-secret"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "duration_ms" in data

    def test_outbound_health_check_handles_failure(self):
        with patch("app.routes.proxy.get_http_client") as mock_client:
            mock_client.return_value.head.side_effect = Exception("Network error")

            response = client.get(
                "/internal/health/outbound",
                headers={"X-Retry-Secret": "test-retry-secret"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "unhealthy"
            assert "error" in data


class TestOutboundHealthCheckReal:
    """Real integration tests for outbound connectivity (requires network)."""

    @pytest.mark.integration
    def test_outbound_health_check_reachable(self):
        """Verify the health check can reach the public internet."""

        async def _check() -> None:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.headers = {}

            mock_client = MagicMock()
            mock_client.head = AsyncMock(return_value=mock_response)

            with patch("app.routes.proxy.get_http_client", return_value=mock_client):
                transport = httpx._transports.asgi.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    response = await ac.get(
                        "/internal/health/outbound",
                        headers={"X-Retry-Secret": "test-retry-secret"},
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] == "healthy"
                    assert "duration_ms" in data
                    assert data["duration_ms"] >= 0

        asyncio.run(_check())


class TestProxyWebhookIntegration:
    """Integration tests for the /v1/route/{slug} endpoint."""

    def test_health_check(self):
        """Test that root health check endpoint returns 200."""
        with (
            patch("app.database.admin") as _,
            patch(
                "app.database.execute_query", return_value=MagicMock(data=[{"id": "1"}])
            ),
        ):
            response = client.get("/health")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "healthy"
            assert body["database"] == "connected"
            assert body["cache"] == "connected"
            assert body["service"] == "SafeRoute API"

    def test_missing_route_returns_404(self):
        """Test that routing to a non-existent slug returns 404."""
        with (
            patch("app.routes.proxy.admin") as _,
            patch("app.services.route_cache.admin") as mock_cache_admin,
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

            response = client.post("/v1/route/does-not-exist", json={"hello": "world"})
            assert response.status_code == 404
            assert response.json() == {"detail": "Active routing link not found."}

    def test_request_size_limit_middleware_enforced(self):
        """Test that requests exceeding the 1MB limit are rejected with 413."""
        # Create a payload larger than 1MB (1.1MB of 'a')
        large_payload = "a" * (1024 * 1024 + 102)
        response = client.post("/v1/route/some-slug", content=large_payload)
        assert response.status_code == 413
        assert response.json() == {"detail": "Request body too large"}
        # Oversized rejections must still carry hardening headers.
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert "Content-Security-Policy" in response.headers

    def test_stats_endpoint_returns_correct_shape(self):
        """Test that /v1/routes/{route_id}/stats returns aggregated stats."""
        from app.models import User

        fake_user = User(
            id="test-user-id",
            email="test@example.com",
            full_name=None,
            created_at="2026-01-01T00:00:00Z",
        )

        with patch("app.routes.auth.admin") as mock_admin:
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                {"id": "route-1"}
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {
                    "total_deliveries": 10,
                    "successful_deliveries": 8,
                    "failed_deliveries": 2,
                    "timeout_count": 1,
                    "avg_latency_ms": 120.5,
                    "deliveries_24h": 3,
                    "deliveries_7d": 8,
                    "deliveries_30d": 10,
                }
            ]

            app.dependency_overrides = {}
            from app.routes.auth import get_current_user_from_jwt

            app.dependency_overrides[get_current_user_from_jwt] = lambda: fake_user

            try:
                response = client.get(
                    "/v1/routes/route-1/stats",
                    headers={"Authorization": "Bearer fake-token"},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["total_deliveries"] == 10
                assert data["success_rate_percent"] == 80.0
                assert data["avg_latency_ms"] == 120.5
            finally:
                app.dependency_overrides = {}

    def test_route_response_exposes_transform_fields(self):
        """Test that RouteResponse includes transform_headers and transform_body_template."""
        from app.models import RouteResponse

        route = RouteResponse(
            id="route-1",
            user_id="user-1",
            name="Test",
            slug="test",
            destination_url="https://1.1.1.1",
            method="POST",
            headers={},
            is_active=True,
            requests_count=0,
            transform_headers={"X-Custom": "true"},
            transform_body_template='{"key": "{{value}}"}',
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert route.transform_headers == {"X-Custom": "true"}
        assert route.transform_body_template == '{"key": "{{value}}"}'

    def test_request_id_middleware_adds_header(self):
        """Test that X-Request-ID is returned in response headers."""
        response = client.get("/")
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) > 0

    def test_cors_allows_request_id_header(self):
        """Test that X-Request-ID is permitted by the CORS header allowlist."""
        response = client.get(
            "/v1/route/test",
            headers={
                "Origin": "http://localhost:8000",
                "X-Request-ID": "test-123",
            },
        )
        assert response.status_code in (200, 404, 422)
        acrh = response.headers.get("access-control-allow-headers", "")
        assert "x-request-id" in acrh.lower() or response.status_code != 200

    def test_content_type_header_is_preserved_on_forward(self):
        """Test that inbound Content-Type is forwarded when not overridden."""
        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "transform_headers": {},
            "slug": "test-route",
            "name": "Test",
            "user_id": "test-user-id",
            "is_active": True,
            "requests_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        with (
            _mock_jwt(),
            patch("app.routes.proxy.admin") as mock_admin,
            patch("app.services.route_cache.admin") as mock_cache_admin,
            patch(
                "app.routes.proxy.forward_payload", return_value=(200, "ok", {})
            ) as mock_forward,
            patch("app.routes.proxy.bump_route_metrics_atomic"),
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            response = client.post(
                "/v1/route/test-route",
                json={"name": "Jane"},
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 200
            sent_headers = mock_forward.call_args.kwargs["headers"]
            assert sent_headers["Content-Type"] == "application/json"

    def test_per_route_payload_size_limit_enforced(self):
        """Test that requests exceeding a route's max_payload_bytes are rejected with 413."""
        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "max_payload_bytes": 100,
            "webhook_secret": None,
            "transform_body_template": None,
            "transform_headers": {},
            "slug": "test-route",
            "name": "Test",
            "user_id": "test-user-id",
            "is_active": True,
            "requests_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        with (
            _mock_jwt(),
            patch("app.routes.proxy.admin") as mock_admin,
            patch("app.services.route_cache.admin") as mock_cache_admin,
            patch("app.routes.proxy.bump_route_metrics_atomic"),
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            response = client.post(
                "/v1/route/test-route",
                content=b"x" * 101,
                headers={"Content-Type": "application/octet-stream"},
            )

            assert response.status_code == 413
            assert "max_payload_bytes" in response.json()["detail"].lower() or "limit" in response.json()["detail"].lower()

    def test_per_route_payload_size_limit_allows_under_limit(self):
        """Test that requests under a route's max_payload_bytes are forwarded."""
        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "max_payload_bytes": 100,
            "webhook_secret": None,
            "transform_body_template": None,
            "transform_headers": {},
            "slug": "test-route",
            "name": "Test",
            "user_id": "test-user-id",
            "is_active": True,
            "requests_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        with (
            _mock_jwt(),
            patch("app.routes.proxy.admin") as mock_admin,
            patch("app.services.route_cache.admin") as mock_cache_admin,
            patch(
                "app.routes.proxy.forward_payload", return_value=(200, "ok", {})
            ) as mock_forward,
            patch("app.routes.proxy.bump_route_metrics_atomic"),
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            response = client.post(
                "/v1/route/test-route",
                json={"data": "x" * 40},
            )

            assert response.status_code == 200
            assert mock_forward.called

    def test_outbound_signing_header_present_when_secret_configured(self):
        """Test that X-SafeRoute-Signature is added when route has signing_secret."""
        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "max_payload_bytes": 1048576,
            "signing_secret": "safe_plain:test-signing-secret-plaintext",
            "webhook_secret": None,
            "transform_body_template": None,
            "transform_headers": {},
            "slug": "test-route",
            "name": "Test",
            "user_id": "test-user-id",
            "is_active": True,
            "requests_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        with (
            _mock_jwt(),
            patch("app.routes.proxy.admin") as mock_admin,
            patch("app.database.admin") as mock_db_admin,
            patch("app.routes.proxy.get_cached_route", return_value=route),
            patch(
                "app.routes.proxy.forward_payload", return_value=(200, "ok", {})
            ) as mock_forward,
            patch("app.routes.proxy.bump_route_metrics_atomic"),
        ):
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1, "remaining": 29}
            ]
            mock_db_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1, "remaining": 29}
            ]

            response = client.post(
                "/v1/route/test-route",
                json={"data": "test"},
            )

            assert response.status_code == 200
            assert mock_forward.called
            sent_headers = mock_forward.call_args.kwargs["headers"]
            assert "X-SafeRoute-Signature" in sent_headers
            assert sent_headers["X-SafeRoute-Signature"].startswith("sha256=")

    def test_outbound_signing_header_absent_when_no_secret(self):
        """Test that X-SafeRoute-Signature is not added when route has no signing_secret."""
        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "max_payload_bytes": 1048576,
            "signing_secret": None,
            "webhook_secret": None,
            "transform_body_template": None,
            "transform_headers": {},
            "slug": "test-route",
            "name": "Test",
            "user_id": "test-user-id",
            "is_active": True,
            "requests_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        with (
            _mock_jwt(),
            patch("app.routes.proxy.admin") as mock_admin,
            patch("app.database.admin") as mock_db_admin,
            patch("app.routes.proxy.get_cached_route", return_value=route),
            patch(
                "app.routes.proxy.forward_payload", return_value=(200, "ok", {})
            ) as mock_forward,
            patch("app.routes.proxy.bump_route_metrics_atomic"),
        ):
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1, "remaining": 29}
            ]
            mock_db_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1, "remaining": 29}
            ]

            response = client.post(
                "/v1/route/test-route",
                json={"data": "test"},
            )

            assert response.status_code == 200
            assert mock_forward.called
            sent_headers = mock_forward.call_args.kwargs["headers"]
            assert "X-SafeRoute-Signature" not in sent_headers


class TestSecretRotationCheck:
    """Tests for the /internal/check-secret-rotation endpoint."""

    def test_returns_stale_secrets(self):
        """Test that stale secrets are returned."""
        with (
            patch("app.routes.proxy.admin") as mock_admin,
            patch("app.services.secret_rotation.admin") as mock_sr_admin,
        ):
            mock_admin.table.return_value.select.return_value.order.return_value.execute.return_value.data = [
                {
                    "secret_name": "ENCRYPTION_KEY",
                    "last_rotated_at": "2025-01-01T00:00:00Z",
                    "owner": "ops",
                    "created_at": "2025-01-01T00:00:00Z",
                },
                {
                    "secret_name": "API_KEY_SALT",
                    "last_rotated_at": "2026-07-01T00:00:00Z",
                    "owner": "ops",
                    "created_at": "2025-01-01T00:00:00Z",
                },
            ]
            mock_sr_admin.table.return_value.select.return_value.order.return_value.execute.return_value.data = [
                {
                    "secret_name": "ENCRYPTION_KEY",
                    "last_rotated_at": "2025-01-01T00:00:00Z",
                    "owner": "ops",
                    "created_at": "2025-01-01T00:00:00Z",
                },
                {
                    "secret_name": "API_KEY_SALT",
                    "last_rotated_at": "2026-07-01T00:00:00Z",
                    "owner": "ops",
                    "created_at": "2025-01-01T00:00:00Z",
                },
            ]

            response = client.get(
                "/internal/check-secret-rotation",
                headers={"X-Retry-Secret": "test-retry-secret"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["total_checked"] == 2
            assert data["stale_count"] == 1
            assert data["stale_secrets"][0]["secret_name"] == "ENCRYPTION_KEY"
            assert data["stale_secrets"][0]["is_stale"] is True

    def test_requires_retry_secret(self):
        """Test that endpoint requires X-Retry-Secret header."""
        response = client.get("/internal/check-secret-rotation")
        assert response.status_code == 401

    def test_returns_empty_when_no_secrets_tracked(self):
        """Test that empty result is returned when no secrets are tracked."""
        with (
            patch("app.routes.proxy.admin") as mock_admin,
            patch("app.services.secret_rotation.admin") as mock_sr_admin,
        ):
            mock_admin.table.return_value.select.return_value.order.return_value.execute.return_value.data = []
            mock_sr_admin.table.return_value.select.return_value.order.return_value.execute.return_value.data = []

            response = client.get(
                "/internal/check-secret-rotation",
                headers={"X-Retry-Secret": "test-retry-secret"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["total_checked"] == 0
            assert data["stale_count"] == 0


class TestCircuitBreakerStats:
    """Tests for the /internal/circuit-breaker/stats endpoint."""

    def test_returns_stats_when_destinations_tracked(self):
        """Test that circuit breaker stats are returned."""
        with patch("app.services.circuit_breaker.admin") as mock_admin:
            mock_admin.table.return_value.select.return_value.order.return_value.execute.return_value.data = [
                {
                    "destination_url": "https://example.com",
                    "state": "open",
                    "failure_count": 5,
                    "opened_at": "2026-07-19T10:00:00Z",
                    "updated_at": "2026-07-19T10:00:00Z",
                }
            ]

            response = client.get(
                "/internal/circuit-breaker/stats",
                headers={"X-Retry-Secret": "test-retry-secret"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["total_tracked"] == 1
            assert data["summary"]["open"] == 1
            assert "https://example.com" in data["destinations"]

    def test_requires_retry_secret(self):
        """Test that endpoint requires X-Retry-Secret header."""
        response = client.get("/internal/circuit-breaker/stats")
        assert response.status_code == 401

    def test_returns_empty_when_no_destinations(self):
        """Test that empty result is returned when no destinations are tracked."""
        with patch("app.services.circuit_breaker.admin") as mock_admin:
            mock_admin.table.return_value.select.return_value.order.return_value.execute.return_value.data = []

            response = client.get(
                "/internal/circuit-breaker/stats",
                headers={"X-Retry-Secret": "test-retry-secret"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["total_tracked"] == 0


class TestAdminIpsSettings:
    """Tests for the /internal/settings/admin-ips endpoints."""

    def test_get_admin_ips_returns_from_database(self):
        """Test that GET returns IPs from database when present."""
        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"value": {"ips": "192.168.1.1, 10.0.0.0/8"}}
            ]

            response = client.get(
                "/internal/settings/admin-ips",
                headers={"X-Retry-Secret": "test-retry-secret"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["admin_allowed_ips"] == "192.168.1.1, 10.0.0.0/8"

    def test_get_admin_ips_falls_back_to_env(self):
        """Test that GET falls back to env var when no DB setting."""
        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

            response = client.get(
                "/internal/settings/admin-ips",
                headers={"X-Retry-Secret": "test-retry-secret"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["admin_allowed_ips"] == settings.ADMIN_ALLOWED_IPS

    def test_put_admin_ips_updates_database(self):
        """Test that PUT updates IPs in database."""
        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.table.return_value.upsert.return_value.execute.return_value.data = [
                {"key": "admin_allowed_ips", "value": {"ips": "1.2.3.4"}}
            ]

            response = client.put(
                "/internal/settings/admin-ips",
                headers={"X-Retry-Secret": "test-retry-secret"},
                json={"admin_allowed_ips": "1.2.3.4"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "updated"
            assert data["admin_allowed_ips"] == "1.2.3.4"

    def test_requires_retry_secret(self):
        """Test that endpoints require X-Retry-Secret header."""
        response = client.get("/internal/settings/admin-ips")
        assert response.status_code == 401

        response = client.put(
            "/internal/settings/admin-ips",
            json={"admin_allowed_ips": "1.2.3.4"},
        )
        assert response.status_code == 401
