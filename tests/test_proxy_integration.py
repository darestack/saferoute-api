"""Integration tests for the proxy webhook endpoints using FastAPI TestClient."""

from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@contextmanager
def _mock_jwt():
    """Mock JWT validation to bypass auth in integration tests."""
    with patch("app.routes.auth._get_cached_jwks") as mock_jwks, \
         patch("app.routes.auth.jwt") as mock_jwt:
        mock_jwks.return_value = {"keys": []}
        mock_jwt.get_unverified_header.return_value = {"kid": "test-kid"}
        mock_jwt.decode.return_value = {"sub": "test-user-id"}
        yield


class TestProxyWebhookIntegration:
    """Integration tests for the /v1/route/{slug} endpoint."""

    def test_health_check(self):
        """Test that root health check endpoint returns 200."""
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {
            "Status": "Healthy",
            "service": "SafeRoute API Engine",
        }

    def test_missing_route_returns_404(self):
        """Test that routing to a non-existent slug returns 404."""
        with patch("app.routes.proxy.admin") as mock_admin:
            # Simulate no route found in the database.
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

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

    def test_stats_endpoint_returns_correct_shape(self):
        """Test that /auth/routes/{route_id}/stats returns aggregated stats."""
        from app.models import User

        fake_user = User(id="test-user-id", email="test@example.com", full_name=None, created_at="2026-01-01T00:00:00Z")

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
                    "/auth/routes/route-1/stats",
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
            destination_url="https://example.com",
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
