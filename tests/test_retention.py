"""Tests for retry correctness, retry-secret auth, and retention cleanup.

These exercise the proxy retry/cleanup internals with the Supabase client
mocked, so they run in CI without a database.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routes.proxy import cleanup, process_retries

_PENDING_ROW = {
    "id": 1,
    "retry_count": 0,
    "request_body": {"a": 1},
    "content_type": "application/json",
    "route_id": "route-1",
    "idempotency_key": None,
    "routes": {
        "destination_url": "https://example.com",
        "method": "POST",
        "headers": {},
        "transform_headers": {},
        "transform_body_template": None,
    },
}


def _mock_settings(mock_settings):
    mock_settings.RETRY_ENDPOINT_SECRET = "secret"
    mock_settings.API_KEY_SALT = "fallback"


class TestRetrySecretAuth:
    """The internal retry/cleanup endpoints must reject bad secrets."""

    def test_missing_secret_returns_401(self):
        with patch("app.routes.proxy.settings") as mock_settings:
            _mock_settings(mock_settings)
            with pytest.raises(HTTPException) as exc:
                asyncio.run(process_retries(request=MagicMock(), x_retry_secret=None))
            assert exc.value.status_code == 401

    def test_wrong_secret_returns_401(self):
        with patch("app.routes.proxy.settings") as mock_settings:
            _mock_settings(mock_settings)
            with pytest.raises(HTTPException) as exc:
                asyncio.run(
                    process_retries(request=MagicMock(), x_retry_secret="wrong")
                )
            assert exc.value.status_code == 401

    def test_valid_secret_passes_auth(self):
        with (
            patch("app.services.retry_processor.admin") as mock_admin,
            patch("app.routes.proxy.settings") as mock_settings,
        ):
            _mock_settings(mock_settings)
            mock_admin.table.return_value.select.return_value.eq.return_value.lte.return_value.lt.return_value.gte.return_value.limit.return_value.execute.return_value.data = []
            response = asyncio.run(
                process_retries(request=MagicMock(), x_retry_secret="secret")
            )
            assert response.processed == 0


class TestRetryAtomicClaim:
    """The claim must be atomic and prevent duplicate deliveries."""

    def test_atomic_claim_prevents_duplicate_delivery(self):
        with (
            patch("app.services.retry_processor.admin") as mock_admin,
            patch("app.routes.proxy.settings") as mock_settings,
            patch(
                "app.routes.proxy.forward_payload",
                new=AsyncMock(return_value=(200, "ok", {})),
            ) as mock_forward,
        ):
            _mock_settings(mock_settings)
            # Two pending rows that would otherwise both be delivered.
            mock_admin.table.return_value.select.return_value.eq.return_value.lte.return_value.lt.return_value.gte.return_value.limit.return_value.execute.return_value.data = [
                _PENDING_ROW,
                {**_PENDING_ROW, "id": 2},
            ]
            # Atomic claim: first attempt succeeds (claims the row), any later
            # attempt returns no row because the UPDATE was guarded on
            # retry_status='pending' and the row is already 'retrying'.
            claim_execute = mock_admin.table.return_value.update.return_value.eq.return_value.eq.return_value.execute
            claim_execute.side_effect = [
                MagicMock(data=[{"id": 1}]),
                MagicMock(data=[]),
            ]

            response = asyncio.run(
                process_retries(request=MagicMock(), x_retry_secret="secret")
            )

            # Exactly one delivery, not two: the second claim found no row.
            assert response.processed == 1
            assert mock_forward.call_count == 1


class TestRetryReaper:
    """Stuck 'retrying' rows must be reaped back to 'pending'."""

    def test_reaper_resets_stuck_retrying_rows(self):
        with (
            patch("app.services.retry_processor.admin") as mock_admin,
            patch("app.routes.proxy.settings") as mock_settings,
        ):
            _mock_settings(mock_settings)
            mock_admin.table.return_value.select.return_value.eq.return_value.lte.return_value.lt.return_value.gte.return_value.limit.return_value.execute.return_value.data = [
                _PENDING_ROW
            ]
            # Claim fails (already claimed) so we just verify the reaper fired.
            mock_admin.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

            asyncio.run(process_retries(request=MagicMock(), x_retry_secret="secret"))

            update_calls = mock_admin.table.return_value.update.call_args_list
            assert any(
                c.args == ({"retry_status": "pending"},) for c in update_calls
            ), "reaper must reset stuck 'retrying' rows to 'pending'"
            eq_calls = (
                mock_admin.table.return_value.update.return_value.eq.call_args_list
            )
            assert any(c.args == ("retry_status", "retrying") for c in eq_calls), (
                "reaper must target retry_status='retrying'"
            )


class TestProxyDestinationValidation:
    """Regression coverage for the proxy destination-validation path."""

    def test_invalid_destination_returns_400_not_crash(self):
        from app.routes.proxy import proxy_webhook, _route_cache

        route = {
            "id": "route-1",
            "destination_url": "http://example.com",  # not HTTPS -> invalid
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "transform_headers": {},
            "slug": "unique-test-route-xyz",
            "name": "Test",
            "user_id": "user-1",
            "is_active": True,
            "requests_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        with (
            patch("app.routes.proxy.admin") as mock_admin,
            patch("app.services.route_cache.admin") as mock_cache_admin,
            patch(
                "app.routes.proxy.forward_payload",
                new=AsyncMock(return_value=(200, "ok", {})),
            ) as mock_forward,
            patch("app.routes.proxy.bump_route_metrics_atomic"),
            patch(
                "app.routes.proxy.verify_api_key",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]
            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("unique-test-route-xyz", route))
            assert "unique-test-route-xyz" in _route_cache

            request = MagicMock()
            request.headers = {}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(return_value=b"{}")

            with pytest.raises(HTTPException) as exc:
                asyncio.run(
                    proxy_webhook(
                        slug="unique-test-route-xyz",
                        request=request,
                        idempotency_key=None,
                        x_api_key=None,
                    )
                )
            # Must be a clean 400, not a NameError/500 from the missing import.
            assert exc.value.status_code == 400
            mock_forward.assert_not_called()


class TestCleanupEndpoint:
    """Retention cleanup endpoint auth + side effects."""

    def test_missing_secret_returns_401(self):
        with patch("app.routes.proxy.settings") as mock_settings:
            _mock_settings(mock_settings)
            with pytest.raises(HTTPException) as exc:
                asyncio.run(cleanup(request=MagicMock(), x_retry_secret=None))
            assert exc.value.status_code == 401

    def test_invokes_all_cleanup_functions(self):
        with (
            patch("app.services.retention.admin") as mock_admin,
            patch("app.routes.proxy.settings") as mock_settings,
        ):
            _mock_settings(mock_settings)
            response = asyncio.run(
                cleanup(request=MagicMock(), x_retry_secret="secret", keep_days=30)
            )

            assert response.keep_days == 30
            rpc_names = [c.args[0] for c in mock_admin.rpc.call_args_list]
            assert "cleanup_webhook_logs" in rpc_names
            assert "cleanup_rate_limits" in rpc_names
            assert "cleanup_pkce_verifiers" in rpc_names
            assert "cleanup_idempotency_cache" in rpc_names

            # Boolean results should be returned as-is (not coerced to counts).
            assert response.rate_limits_cleaned is True
            assert response.pkce_verifiers_cleaned is True
            assert response.idempotency_cache_cleaned is True


class TestRetryCircuitBreakerInteraction:
    """When the circuit breaker is open, retries return 503 immediately."""

    def test_circuit_breaker_open_returns_503(self):
        from app.routes.proxy import process_retries

        with (
            patch("app.services.retry_processor.admin") as mock_admin,
            patch("app.routes.proxy.settings") as mock_settings,
            patch(
                "app.routes.proxy._is_circuit_breaker_open",
                return_value=True,
            ),
            patch(
                "app.routes.proxy.get_http_client",
            ) as mock_http_client,
        ):
            _mock_settings(mock_settings)
            mock_admin.table.return_value.select.return_value.eq.return_value.lte.return_value.lt.return_value.gte.return_value.limit.return_value.execute.return_value.data = [
                _PENDING_ROW
            ]

            response = asyncio.run(
                process_retries(
                    request=MagicMock(),
                    x_retry_secret="secret",
                )
            )

            # Circuit breaker open → forward_payload should return 503
            # without ever calling the HTTP client.
            assert response.processed == 1
            assert response.results[0]["status_code"] == 503
            # 503 is retryable, so with retry_count=0 and max_retries=3,
            # the outcome should be "pending" for another attempt.
            assert response.results[0]["outcome"] == "pending"
            mock_http_client.assert_not_called()
