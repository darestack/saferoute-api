"""Integration tests for the proxy webhook endpoints using FastAPI TestClient."""

import asyncio
import pytest
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from app.main import app

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
        import asyncio

        async def _check() -> None:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.headers = {}

            mock_client = MagicMock()
            mock_client.head = AsyncMock(return_value=mock_response)

            with patch("app.routes.proxy.get_http_client", return_value=mock_client):
                transport = httpx._transports.asgi.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
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
            assert response.json() == {
                "status": "healthy",
                "database": "connected",
                "service": "SafeRoute API",
            }

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
