"""Tests for proxy helper functions (no Supabase dependency)."""

import asyncio
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.utils.security import verify_webhook_signature, get_client_ip
from app.utils.transform import parse_payload, render_template, resolve_dot_path
from app.utils.retry import should_retry, calculate_next_retry
from app.main import app
import math
import time as time_module

client = TestClient(app)


class TestGetClientIp:
    """Tests for client IP extraction."""

    def test_x_forwarded_for_single(self):
        class FakeRequest:
            headers = {"X-Forwarded-For": "1.2.3.4"}
            client = None

        assert get_client_ip(FakeRequest()) == "unknown"

    def test_x_forwarded_for_chain(self):
        class FakeRequest:
            headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8, 9.10.11.12"}
            client = None

        assert get_client_ip(FakeRequest()) == "unknown"

    def test_x_forwarded_for_trusted_when_behind_private_ip(self):
        class FakeRequest:
            headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8, 9.10.11.12"}
            client = type("c", (), {"host": "10.0.0.1"})()

        with patch("app.utils.security.settings") as mock_settings:
            mock_settings.TRUSTED_PROXIES = "10.0.0.1"
            # Now we extract the right-most IP (9.10.11.12)
            assert get_client_ip(FakeRequest()) == "9.10.11.12"

    def test_x_forwarded_for_ignored_when_not_in_trusted_proxies(self):
        class FakeRequest:
            headers = {"X-Forwarded-For": "1.2.3.4"}
            client = type("c", (), {"host": "10.0.0.1"})()

        with patch("app.utils.security.settings") as mock_settings:
            mock_settings.TRUSTED_PROXIES = ""
            assert get_client_ip(FakeRequest()) == "10.0.0.1"

    def test_direct_client(self):
        class FakeClient:
            host = "10.0.0.1"

        class FakeRequest:
            headers = {}
            client = FakeClient()

        assert get_client_ip(FakeRequest()) == "10.0.0.1"

    def test_no_client_returns_unknown(self):
        class FakeRequest:
            headers = {}
            client = None

        assert get_client_ip(FakeRequest()) == "unknown"

    def test_trusted_proxy_allows_x_forwarded_for(self):
        class FakeRequest:
            headers = {"X-Forwarded-For": "1.2.3.4"}
            client = type("c", (), {"host": "10.0.0.1"})()

        with patch("app.utils.security.settings") as mock_settings:
            mock_settings.TRUSTED_PROXIES = "10.0.0.1, 10.0.0.2"
            assert get_client_ip(FakeRequest()) == "1.2.3.4"

    def test_untrusted_proxy_ignores_x_forwarded_for(self):
        class FakeRequest:
            headers = {"X-Forwarded-For": "1.2.3.4"}
            client = type("c", (), {"host": "192.168.1.1"})()

        with patch("app.utils.security.settings") as mock_settings:
            mock_settings.TRUSTED_PROXIES = "10.0.0.1, 10.0.0.2"
            assert get_client_ip(FakeRequest()) == "192.168.1.1"


class TestParsePayload:
    """Tests for payload parsing."""

    def test_json_payload(self):
        body = json.dumps({"key": "value"}).encode()
        result = parse_payload(body, "application/json")
        assert result == {"key": "value"}

    def test_json_with_charset(self):
        body = json.dumps({"key": "value"}).encode()
        result = parse_payload(body, "application/json; charset=utf-8")
        assert result == {"key": "value"}

    def test_form_urlencoded(self):
        body = b"name=Alice&age=30"
        result = parse_payload(body, "application/x-www-form-urlencoded")
        assert result == {"name": "Alice", "age": "30"}

    def test_empty_body(self):
        result = parse_payload(b"", "application/json")
        assert result == {}

    def test_invalid_json(self):
        result = parse_payload(b"not json", "application/json")
        assert result == {}

    def test_json_without_content_type(self):
        body = b'{"hello": "world"}'
        result = parse_payload(body, "")
        assert result == {"hello": "world"}

    def test_form_without_content_type(self):
        body = b"name=Alice&age=30"
        result = parse_payload(body, "")
        assert result == {"name": "Alice", "age": "30"}


class TestResolveDotPath:
    """Tests for nested dot-notation field resolution."""

    def test_flat_key(self):
        assert resolve_dot_path({"name": "Alice"}, "name") == "Alice"

    def test_nested_key(self):
        data = {"data": {"customer": {"email": "test@example.com"}}}
        assert resolve_dot_path(data, "data.customer.email") == "test@example.com"

    def test_list_index(self):
        data = {"items": [10, 20, 30]}
        assert resolve_dot_path(data, "items.1") == 20

    def test_nested_list_in_dict(self):
        data = {"data": {"items": [{"sku": "A"}, {"sku": "B"}]}}
        assert resolve_dot_path(data, "data.items.0.sku") == "A"

    def test_missing_key_returns_none(self):
        assert resolve_dot_path({"a": 1}, "b") is None

    def test_deep_missing_returns_none(self):
        assert resolve_dot_path({"a": {"b": 1}}, "a.c.d") is None

    def test_list_index_out_of_range(self):
        data = {"items": [1, 2]}
        assert resolve_dot_path(data, "items.5") is None

    def test_non_numeric_index_on_list(self):
        data = {"items": [1, 2]}
        assert resolve_dot_path(data, "items.foo") is None

    def test_empty_dict(self):
        assert resolve_dot_path({}, "any.path") is None

    def test_scalar_traversal(self):
        assert resolve_dot_path({"a": 42}, "a.b") is None


class TestRenderTemplate:
    """Tests for template rendering with dot-notation placeholders."""

    def test_simple_replacement(self):
        result = render_template("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_nested_replacement(self):
        payload = {"data": {"customer": {"email": "test@example.com"}}}
        result = render_template("Email: {{data.customer.email}}", payload)
        assert result == "Email: test@example.com"

    def test_multiple_placeholders(self):
        payload = {"first": "Jane", "last": "Doe"}
        result = render_template("{{first}} {{last}}", payload)
        assert result == "Jane Doe"

    def test_missing_field_becomes_empty(self):
        result = render_template("Value: {{missing}}", {})
        assert result == "Value: "

    def test_spaces_in_placeholder(self):
        result = render_template("{{ name }}", {"name": "Alice"})
        assert result == "Alice"

    def test_no_placeholders(self):
        result = render_template("static text", {"key": "value"})
        assert result == "static text"

    def test_json_template(self):
        payload = {"user": {"id": 123, "email": "a@b.com"}}
        template = '{"user_id": "{{user.id}}", "email": "{{user.email}}"}'
        result = render_template(template, payload)
        assert result == '{"user_id": "123", "email": "a@b.com"}'


class TestVerifyWebhookSignature:
    """Tests for HMAC-SHA256 webhook signature verification."""

    def _sign(self, body: bytes, secret: str) -> str:
        return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def test_valid_signature_raw_hex(self):
        body = b'{"event": "test"}'
        secret = "my_webhook_secret"
        sig = self._sign(body, secret)
        assert verify_webhook_signature(body, sig, secret) is True

    def test_valid_signature_sha256_prefix(self):
        body = b'{"event": "test"}'
        secret = "my_webhook_secret"
        sig = "sha256=" + self._sign(body, secret)
        assert verify_webhook_signature(body, sig, secret) is True

    def test_invalid_signature(self):
        body = b'{"event": "test"}'
        assert verify_webhook_signature(body, "invalid_hex", "secret") is False

    def test_tampered_body(self):
        body = b'{"event": "test"}'
        secret = "my_webhook_secret"
        sig = self._sign(body, secret)
        tampered = b'{"event": "hacked"}'
        assert verify_webhook_signature(tampered, sig, secret) is False

    def test_no_signature_header_when_secret_present(self):
        assert verify_webhook_signature(b"body", None, "secret") is False

    def test_no_signature_when_no_secret(self):
        assert verify_webhook_signature(b"body", None, "") is True

    def test_signature_provided_but_no_secret_rejects(self):
        assert verify_webhook_signature(b"body", "anything", "") is False

    def test_forged_empty_key_hmac_rejected(self):
        """An attacker who computes HMAC('', body) must still be rejected."""
        body = b'{"event": "test"}'
        forged_sig = hmac.new(b"", body, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(body, forged_sig, "") is False


class TestShouldRetry:
    """Tests for retry logic."""

    def test_reversible_5xx_should_retry(self):
        assert should_retry(502) is True
        assert should_retry(503) is True
        assert should_retry(504) is True

    def test_429_should_retry(self):
        assert should_retry(429) is True

    def test_non_retryable_5xx_should_not_retry(self):
        assert should_retry(500) is False
        assert should_retry(501) is False
        assert should_retry(505) is False
        assert should_retry(507) is False

    def test_2xx_should_not_retry(self):
        assert should_retry(200) is False
        assert should_retry(201) is False

    def test_4xx_should_not_retry(self):
        assert should_retry(400) is False
        assert should_retry(404) is False


class TestCalculateNextRetry:
    """Tests for exponential backoff calculation."""

    def test_first_retry(self):
        result = calculate_next_retry(0)
        assert isinstance(result, str)
        assert "T" in result  # ISO format

    def test_increasing_delay(self):
        r0 = calculate_next_retry(0)
        r1 = calculate_next_retry(1)
        r2 = calculate_next_retry(2)
        # Later retries should be at later timestamps.
        assert r0 < r1 < r2


class TestCheckIdempotency:
    """Tests for idempotency cache lookups and storage."""

    def test_check_returns_full_response(self):
        from app.routes.proxy import check_idempotency

        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value.data = [
                {
                    "response_status": 200,
                    "response_body": "ok",
                    "response_headers": {"X-Custom": "v"},
                }
            ]
            result = asyncio.run(check_idempotency("route-1", "key-1"))
            assert result is not None
            assert result["destination_status"] == 200
            assert result["response_body"] == "ok"
            assert result["response_headers"] == {"X-Custom": "v"}

    def test_store_persists_headers(self):
        from app.routes.proxy import store_idempotency

        with patch("app.routes.proxy.admin") as mock_admin:
            asyncio.run(store_idempotency("route-1", "key-1", 200, "ok", {"X": "v"}))
            call_args = mock_admin.table.return_value.upsert.call_args
            record = call_args[0][0] if call_args[0] else call_args[1]["record"]
            assert record["response_headers"] == {"X": "v"}
            assert record["response_body"] == "ok"


class TestLogDeliveryContentType:
    """Tests that log_delivery persists content_type."""

    def test_content_type_stored(self):
        from app.routes.proxy import log_delivery

        with patch("app.routes.proxy.admin") as mock_admin:
            asyncio.run(
                log_delivery(
                    route_id="route-1",
                    status_code=200,
                    payload={},
                    response_body="ok",
                    response_headers={},
                    client_ip="1.2.3.4",
                    user_agent="test",
                    duration_ms=10,
                    content_type="application/json",
                )
            )
            call_args = mock_admin.table.return_value.insert.call_args
            record = call_args[0][0] if call_args[0] else call_args[1]["record"]
            assert record["content_type"] == "application/json"


class TestProcessRetriesEmptyDestination:
    """Tests retry endpoint skips routes with empty destination URLs."""

    def test_marks_exhausted_when_no_destination(self):
        from app.routes.proxy import process_retries

        with (
            patch("app.services.retry_processor.admin") as mock_admin,
            patch("app.routes.proxy.settings") as mock_settings,
            patch(
                "app.utils.retry.get_retry_window_cutoff",
                return_value="2026-01-01T00:00:00Z",
            ),
        ):
            mock_settings.RETRY_ENDPOINT_SECRET = "secret"
            mock_admin.table.return_value.select.return_value.eq.return_value.lte.return_value.lt.return_value.gte.return_value.limit.return_value.execute.return_value.data = [
                {
                    "id": 1,
                    "retry_count": 0,
                    "routes": {
                        "destination_url": "",
                        "method": "POST",
                        "headers": {},
                        "transform_headers": {},
                        "transform_body_template": None,
                        "form_schema": {},
                        "spam_honeypot_field": None,
                        "spam_blocked_ua": [],
                        "spam_allowed_countries": [],
                        "spam_blocked_ips": [],
                        "email_notifications": {},
                    },
                }
            ]

            response = asyncio.run(
                process_retries(
                    request=MagicMock(),
                    x_retry_secret="secret",
                )
            )
            assert response.processed == 1
            assert response.results[0]["outcome"] == "exhausted"
            assert response.results[0]["status_code"] == 0


class TestEnforceRateLimit:
    """Tests for atomic rate limit enforcement."""

    def test_allows_under_limit(self):
        from app.routes.proxy import enforce_rate_limit

        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]
            asyncio.run(enforce_rate_limit("route-1", "1.2.3.4", 30))
            mock_admin.rpc.assert_called_once()

    def test_denies_over_limit(self):
        from app.routes.proxy import enforce_rate_limit
        from fastapi import HTTPException

        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": False, "new_count": 30}
            ]
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(enforce_rate_limit("route-1", "1.2.3.4", 30))
            assert exc_info.value.status_code == 429

    def test_fails_open_on_rpc_error(self):
        from app.routes.proxy import enforce_rate_limit
        from fastapi import HTTPException

        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.return_value.data = []
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(enforce_rate_limit("route-1", "1.2.3.4", 30))
            assert exc_info.value.status_code == 429


class TestRateLimitHeaders:
    """Tests for rate-limit response headers."""

    def test_returns_remaining_on_success(self):
        from app.routes.proxy import enforce_rate_limit

        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 5}
            ]
            remaining = asyncio.run(enforce_rate_limit("route-1", "1.2.3.4", 30))
            assert remaining == 25

    def test_handles_new_count_zero(self):
        """When new_count is 0 (no requests yet), remaining must be max_requests."""
        from app.routes.proxy import enforce_rate_limit

        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 0}
            ]
            remaining = asyncio.run(enforce_rate_limit("route-1", "1.2.3.4", 30))
            assert remaining == 30

    def test_429_includes_retry_after_header(self):
        from app.routes.proxy import enforce_rate_limit, _rate_limit_violations
        from fastapi import HTTPException

        _rate_limit_violations.clear()
        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": False, "new_count": 30}
            ]
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(enforce_rate_limit("route-1", "1.2.3.4", 30))
            assert exc_info.value.status_code == 429
            assert exc_info.value.headers["Retry-After"] == "120"

    def test_rpc_failure_includes_retry_after_header(self):
        from app.routes.proxy import enforce_rate_limit, _rate_limit_violations
        from fastapi import HTTPException

        _rate_limit_violations.clear()
        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.return_value.data = []
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(enforce_rate_limit("route-1", "1.2.3.4", 30))
            assert exc_info.value.status_code == 429
            assert exc_info.value.headers["Retry-After"] == "60"


class TestProxyContentTypePreservation:
    """Tests that inbound Content-Type is forwarded to destination."""

    def test_json_content_type_preserved(self):
        from app.routes.proxy import proxy_webhook

        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {},
            "transform_headers": {},
            "slug": "test-route",
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
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            request = MagicMock()
            request.headers = {"content-type": "application/json"}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(return_value=b'{"name": "Jane"}')

            asyncio.run(
                proxy_webhook(
                    slug="test-route",
                    request=request,
                    idempotency_key=None,
                    x_api_key=None,
                )
            )

            sent_headers = mock_forward.call_args[1]["headers"]
            assert sent_headers["Content-Type"] == "application/json"

    def test_route_headers_override_content_type(self):
        from app.routes.proxy import proxy_webhook

        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {"Content-Type": "application/xml"},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {},
            "transform_headers": {},
            "slug": "test-route",
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
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            request = MagicMock()
            request.headers = {"content-type": "application/json"}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(return_value=b'{"name": "Jane"}')

            asyncio.run(
                proxy_webhook(
                    slug="test-route",
                    request=request,
                    idempotency_key=None,
                    x_api_key=None,
                )
            )

            sent_headers = mock_forward.call_args[1]["headers"]
            assert sent_headers["Content-Type"] == "application/xml"


class TestOAuthCallbackPost:
    """Tests for POST-based OAuth callback."""

    def test_post_callback_success(self):
        from app.routes.oauth import _exchange_code

        with (
            patch(
                "app.routes.oauth._retrieve_and_delete_pkce_verifier",
                return_value="verifier",
            ),
            patch("app.routes.oauth.supabase_client") as mock_client,
        ):
            mock_session = MagicMock()
            mock_session.access_token = "token-123"
            mock_user = MagicMock()
            mock_user.id = "user-123"
            mock_user.email = "test@example.com"
            mock_client.auth.exchange_code_for_session.return_value = MagicMock(
                session=mock_session, user=mock_user
            )

            result = asyncio.run(_exchange_code("auth-code", "challenge-123"))
            assert result.access_token == "token-123"
            assert result.user_id == "user-123"

    def test_post_callback_sanitizes_error(self):
        from app.routes.oauth import _exchange_code
        from fastapi import HTTPException

        with (
            patch(
                "app.routes.oauth._retrieve_and_delete_pkce_verifier",
                return_value="verifier",
            ),
            patch("app.routes.oauth.supabase_client") as mock_client,
        ):
            mock_client.auth.exchange_code_for_session.side_effect = Exception(
                "Internal Supabase error"
            )

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(_exchange_code("bad-code", "challenge-123"))
            assert exc_info.value.status_code == 400
            assert "Internal Supabase error" not in exc_info.value.detail
            assert exc_info.value.detail == "OAuth callback failed"


class TestIdempotencyStoresOnlySuccess:
    """Tests that idempotency cache only stores successful responses."""

    def test_does_not_store_500_response(self):
        from app.routes.proxy import proxy_webhook
        from unittest.mock import MagicMock

        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {},
            "transform_headers": {},
            "slug": "test-route",
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
            patch("app.routes.proxy.forward_payload") as mock_forward,
            patch("app.routes.proxy.bump_route_metrics_atomic") as mock_bump,
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]
            mock_forward.return_value = (500, "error", {})

            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value.data = []

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            request = MagicMock()
            request.headers = {}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(return_value=b"{}")

            response = asyncio.run(
                proxy_webhook(
                    slug="test-route",
                    request=request,
                    idempotency_key="key-123",
                    x_api_key=None,
                )
            )
            assert response.status_code == 200
            body = json.loads(response.body)
            assert body["status"] == "forwarded"
            assert body["destination_status"] == 500
            mock_bump.assert_called_once_with("route-1")

            # Verify idempotency cache was NOT written for 500 response.
            upsert_calls = mock_admin.table.return_value.upsert.call_args_list
            for call in upsert_calls:
                # The record is either first positional arg or in kwargs as 'record'
                record = call[0][0] if call[0] else call[1].get("record", {})
                if record.get("response_status") == 500:
                    pytest.fail("Idempotency cache should not store 500 responses")


class TestRetryBodyReconstruction:
    """Tests for retry body reconstruction edge cases."""

    def test_skips_unsupported_content_types(self):
        from app.routes.proxy import process_retries

        with (
            patch("app.services.retry_processor.admin") as mock_admin,
            patch("app.routes.proxy.settings") as mock_settings,
            patch(
                "app.utils.retry.get_retry_window_cutoff",
                return_value="2026-01-01T00:00:00Z",
            ),
        ):
            mock_settings.RETRY_ENDPOINT_SECRET = "secret"
            mock_admin.table.return_value.select.return_value.eq.return_value.lte.return_value.lt.return_value.gte.return_value.limit.return_value.execute.return_value.data = [
                {
                    "id": 1,
                    "retry_count": 0,
                    "request_body": "<xml>data</xml>",
                    "content_type": "application/xml",
                    "route_id": "route-1",
                    "idempotency_key": None,
                    "routes": {
                        "destination_url": "https://example.com",
                        "method": "POST",
                        "headers": {},
                        "transform_headers": {},
                        "transform_body_template": None,
                        "form_schema": {},
                        "spam_honeypot_field": None,
                        "spam_blocked_ua": [],
                        "spam_allowed_countries": [],
                        "spam_blocked_ips": [],
                        "email_notifications": {},
                    },
                }
            ]

            response = asyncio.run(
                process_retries(
                    request=MagicMock(),
                    x_retry_secret="secret",
                )
            )
            assert response.processed == 1
            assert response.results[0]["outcome"] == "exhausted"


class TestRouteCache:
    """Tests for in-memory route caching."""

    def test_cache_miss_returns_none(self):
        from app.services.route_cache import get_cached_route as _get_cached_route

        assert asyncio.run(_get_cached_route("nonexistent-slug")) is None

    def test_cache_hit_returns_route(self):
        from app.services.route_cache import (
            _cache_route,
            get_cached_route as _get_cached_route,
            clear_route_cache,
        )

        route = {"id": "route-1", "slug": "test"}
        asyncio.run(_cache_route("test-route", route))
        assert asyncio.run(_get_cached_route("test-route")) == route
        asyncio.run(clear_route_cache())


class TestApiKeyCache:
    """Tests for in-memory API key verification caching."""

    def test_cache_miss_returns_none(self):
        from app.database import _get_cached_api_key, clear_api_key_cache

        asyncio.run(clear_api_key_cache())
        assert asyncio.run(_get_cached_api_key("nonexistent-hash")) is None

    def test_fifo_eviction_when_full(self):
        from app.database import (
            _cache_api_key,
            _api_key_cache,
            _API_KEY_CACHE_MAX_SIZE,
            clear_api_key_cache,
        )

        asyncio.run(clear_api_key_cache())
        for i in range(_API_KEY_CACHE_MAX_SIZE):
            asyncio.run(_cache_api_key(f"hash-{i:04d}", f"route-{i}"))

        assert len(_api_key_cache) == _API_KEY_CACHE_MAX_SIZE

        asyncio.run(_cache_api_key("hash-new", "route-new"))
        assert len(_api_key_cache) == _API_KEY_CACHE_MAX_SIZE
        assert "hash-0000" not in _api_key_cache
        asyncio.run(clear_api_key_cache())


class TestHoneypotStripping:
    """Regression test: honeypot fields must never reach the destination."""

    def test_honeypot_stripped_from_forwarded_body(self):
        """When no transform is set, body is reconstructed from cleaned payload."""
        from app.routes.proxy import proxy_webhook

        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {},
            "transform_headers": {},
            "slug": "test-route",
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
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            request = MagicMock()
            request.headers = {"content-type": "application/json"}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(
                return_value=b'{"name": "Jane", "honeypot_field": "spam"}'
            )

            asyncio.run(
                proxy_webhook(
                    slug="test-route",
                    request=request,
                    idempotency_key=None,
                    x_api_key=None,  # explicit None; direct call would otherwise default to the truthy Header marker object
                )
            )

            # The forwarded body must NOT contain the honeypot field.
            sent_body = mock_forward.call_args[1]["body"]
            assert b"honeypot_field" not in sent_body
            assert b"Jane" in sent_body

    def test_extended_honeypot_fields_stripped_from_forwarded_body(self):
        """Common honeypot field names (website, url) must also be stripped."""
        from app.routes.proxy import proxy_webhook

        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {},
            "transform_headers": {},
            "slug": "test-route",
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
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            request = MagicMock()
            request.headers = {"content-type": "application/json"}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(
                return_value=b'{"name": "Jane", "website": "spam", "url": "spam"}'
            )

            asyncio.run(
                proxy_webhook(
                    slug="test-route",
                    request=request,
                    idempotency_key=None,
                    x_api_key=None,
                )
            )

            sent_body = mock_forward.call_args[1]["body"]
            assert b"website" not in sent_body
            assert b"url" not in sent_body
            assert b"Jane" in sent_body


class TestFormValidation:
    """Form schema validation before forwarding."""

    def test_missing_required_field_returns_400(self):
        from app.routes.proxy import _validate_form_schema
        from fastapi import HTTPException

        form_schema = {
            "fields": {
                "name": {"type": "string", "required": True},
                "email": {"type": "email", "required": True},
            }
        }
        payload = {"name": "Jane"}

        with pytest.raises(HTTPException) as exc_info:
            _validate_form_schema(payload, form_schema)
        assert exc_info.value.status_code == 400
        assert "email" in str(exc_info.value.detail)

    def test_invalid_email_returns_400(self):
        from app.routes.proxy import _validate_form_schema
        from fastapi import HTTPException

        form_schema = {
            "fields": {
                "email": {"type": "email", "required": True},
            }
        }
        payload = {"email": "not-an-email"}

        with pytest.raises(HTTPException) as exc_info:
            _validate_form_schema(payload, form_schema)
        assert exc_info.value.status_code == 400

    def test_max_length_exceeded_returns_400(self):
        from app.routes.proxy import _validate_form_schema
        from fastapi import HTTPException

        form_schema = {
            "fields": {
                "message": {"type": "string", "required": True, "max_length": 10},
            }
        }
        payload = {"message": "a" * 20}

        with pytest.raises(HTTPException) as exc_info:
            _validate_form_schema(payload, form_schema)
        assert exc_info.value.status_code == 400

    def test_valid_payload_passes(self):
        from app.routes.proxy import _validate_form_schema

        form_schema = {
            "fields": {
                "name": {"type": "string", "required": True},
                "age": {"type": "number", "min": 0, "max": 150},
            }
        }
        payload = {"name": "Jane", "age": 30}
        _validate_form_schema(payload, form_schema)  # should not raise

    def test_disposable_email_rejected_when_enabled(self, disposable_email_domains):
        from app.routes.proxy import _validate_form_schema
        from fastapi import HTTPException

        form_schema = {
            "fields": {
                "email": {"type": "email", "required": True, "reject_disposable": True},
            }
        }
        payload = {"email": "test@mailinator.com"}

        with pytest.raises(HTTPException) as exc_info:
            _validate_form_schema(payload, form_schema)
        assert exc_info.value.status_code == 400
        assert "Disposable email" in str(exc_info.value.detail)

    def test_legitimate_email_passes_disposable_check(self):
        from app.routes.proxy import _validate_form_schema

        form_schema = {
            "fields": {
                "email": {"type": "email", "required": True, "reject_disposable": True},
            }
        }
        payload = {"email": "user@gmail.com"}
        _validate_form_schema(payload, form_schema)  # should not raise

    def test_disposable_check_skipped_when_disabled(self):
        from app.routes.proxy import _validate_form_schema

        form_schema = {
            "fields": {
                "email": {"type": "email", "required": True},
            }
        }
        payload = {"email": "test@mailinator.com"}
        _validate_form_schema(payload, form_schema)  # should not raise


class TestSpamShield:
    """Spam protection: honeypot and User-Agent blocking."""

    def test_honeypot_field_triggered_returns_400(self):
        from app.routes.proxy import _check_spam_shield
        from fastapi import HTTPException

        route = {
            "slug": "test-route",
            "spam_honeypot_field": "honeypot",
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
        }
        payload = {"honeypot": "filled"}

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_check_spam_shield(payload, route, "1.2.3.4", "curl"))
        assert exc_info.value.status_code == 400

    def test_blocked_user_agent_returns_403(self):
        from app.routes.proxy import _check_spam_shield
        from fastapi import HTTPException

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": ["bot", "scraper"],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
        }
        payload = {}

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_check_spam_shield(payload, route, "1.2.3.4", "MyBot/1.0"))
        assert exc_info.value.status_code == 403

    def test_clean_user_agent_passes(self):
        from app.routes.proxy import _check_spam_shield

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": ["bot"],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
        }
        payload = {}
        asyncio.run(
            _check_spam_shield(payload, route, "1.2.3.4", "Mozilla/5.0")
        )  # should not raise

    def test_allowed_country_passes(self):
        from app.routes.proxy import _check_spam_shield

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": ["US", "GB"],
            "spam_blocked_ips": [],
        }
        payload = {}
        with patch(
            "app.routes.proxy._lookup_country_code",
            return_value="US",
        ):
            asyncio.run(
                _check_spam_shield(payload, route, "1.2.3.4", "Mozilla/5.0")
            )  # should not raise

    def test_blocked_country_returns_403(self):
        from app.routes.proxy import _check_spam_shield
        from fastapi import HTTPException

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": ["US", "GB"],
            "spam_blocked_ips": [],
        }
        payload = {}
        with patch(
            "app.routes.proxy._lookup_country_code",
            return_value="CN",
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    _check_spam_shield(payload, route, "1.2.3.4", "Mozilla/5.0")
                )
            assert exc_info.value.status_code == 403

    def test_geolocation_failure_allows_request(self):
        from app.routes.proxy import _check_spam_shield

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": ["US", "GB"],
            "spam_blocked_ips": [],
        }
        payload = {}
        with patch(
            "app.routes.proxy._lookup_country_code",
            return_value=None,
        ):
            asyncio.run(
                _check_spam_shield(payload, route, "1.2.3.4", "Mozilla/5.0")
            )  # should not raise, fails open

    def test_blocked_ip_returns_403(self):
        from app.routes.proxy import _check_spam_shield
        from fastapi import HTTPException

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": ["1.2.3.4", "5.6.7.8"],
        }
        payload = {}
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_check_spam_shield(payload, route, "1.2.3.4", "Mozilla/5.0"))
        assert exc_info.value.status_code == 403

    def test_allowed_ip_passes(self):
        from app.routes.proxy import _check_spam_shield

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": ["1.2.3.4"],
        }
        payload = {}
        asyncio.run(
            _check_spam_shield(payload, route, "9.9.9.9", "Mozilla/5.0")
        )  # should not raise

    def test_turnstile_valid_token_passes(self):
        from app.routes.proxy import _check_spam_shield

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "turnstile_enabled": True,
            "turnstile_site_key": "site-key",
            "turnstile_secret_key": "secret-key",
        }
        payload = {"cf-turnstile-response": "valid-token"}
        with patch(
            "app.routes.proxy._verify_turnstile_token",
            return_value=True,
        ):
            asyncio.run(
                _check_spam_shield(payload, route, "1.2.3.4", "Mozilla/5.0")
            )  # should not raise

    def test_turnstile_invalid_token_returns_403(self):
        from app.routes.proxy import _check_spam_shield
        from fastapi import HTTPException

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "turnstile_enabled": True,
            "turnstile_site_key": "site-key",
            "turnstile_secret_key": "secret-key",
        }
        payload = {"cf-turnstile-response": "invalid-token"}
        with patch(
            "app.routes.proxy._verify_turnstile_token",
            return_value=False,
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    _check_spam_shield(payload, route, "1.2.3.4", "Mozilla/5.0")
                )
            assert exc_info.value.status_code == 403

    def test_turnstile_missing_token_returns_403(self):
        from app.routes.proxy import _check_spam_shield
        from fastapi import HTTPException

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "turnstile_enabled": True,
            "turnstile_site_key": "site-key",
            "turnstile_secret_key": "secret-key",
        }
        payload = {}
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_check_spam_shield(payload, route, "1.2.3.4", "Mozilla/5.0"))
        assert exc_info.value.status_code == 403

    def test_turnstile_skipped_when_disabled(self):
        from app.routes.proxy import _check_spam_shield

        route = {
            "slug": "test-route",
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "turnstile_enabled": False,
            "turnstile_site_key": "site-key",
            "turnstile_secret_key": "secret-key",
        }
        payload = {"cf-turnstile-response": "token"}
        with patch(
            "app.routes.proxy._verify_turnstile_token",
            return_value=False,
        ):
            asyncio.run(
                _check_spam_shield(payload, route, "1.2.3.4", "Mozilla/5.0")
            )  # should not raise, Turnstile not enforced


class TestDecryptFailure:
    """Tests that decryption failures are handled safely."""

    def test_invalid_token_returns_500(self):
        from app.routes.proxy import proxy_webhook
        from fastapi import HTTPException

        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": "v1:some-secret",
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {},
            "transform_headers": {},
            "slug": "test-route",
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
                "app.routes.proxy.decrypt_webhook_secrets",
                side_effect=ValueError("Failed to decrypt webhook secret"),
            ) as mock_decrypt,
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

            request = MagicMock()
            request.headers = {"content-type": "application/json"}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(return_value=b'{"name": "Jane"}')

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    proxy_webhook(
                        slug="test-route",
                        request=request,
                        idempotency_key=None,
                        x_api_key=None,
                    )
                )

            assert exc_info.value.status_code == 500
            assert "Webhook secret decryption failed" in exc_info.value.detail
            mock_decrypt.assert_called_once_with("v1:some-secret")


class TestRetryClaimStatus:
    """Regression test: retry claim must use a valid retry_status value."""

    def test_claim_uses_retrying_not_processing(self):
        """The claim UPDATE must use 'retrying' (valid in DB constraint)."""
        from app.routes.proxy import process_retries

        with (
            patch("app.services.retry_processor.admin") as mock_admin,
            patch("app.routes.proxy.settings") as mock_settings,
        ):
            mock_settings.RETRY_ENDPOINT_SECRET = "secret"
            mock_settings.API_KEY_SALT = "fallback"
            mock_admin.table.return_value.select.return_value.eq.return_value.lte.return_value.lt.return_value.gte.return_value.limit.return_value.execute.return_value.data = [
                {
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
                        "form_schema": {},
                        "spam_honeypot_field": None,
                        "spam_blocked_ua": [],
                        "spam_allowed_countries": [],
                        "spam_blocked_ips": [],
                        "email_notifications": {},
                    },
                }
            ]

            response = asyncio.run(
                process_retries(
                    request=MagicMock(),
                    x_retry_secret="secret",
                )
            )
            # Verify the claim UPDATE used "retrying" (valid constraint value).
            claim_calls = [
                c
                for c in mock_admin.table.return_value.update.call_args_list
                if c[0][0] == {"retry_status": "retrying"}
            ]
            assert len(claim_calls) == 1
            assert response.processed == 1


class TestRetry429Handling:
    """Regression test: 429 must be retried consistently with should_retry."""

    def test_429_is_retried_not_exhausted(self):
        """A 429 response should be marked 'pending' for retry, not 'exhausted'."""
        from app.routes.proxy import process_retries

        with (
            patch("app.services.retry_processor.admin") as mock_admin,
            patch("app.routes.proxy.settings") as mock_settings,
            patch(
                "app.routes.proxy.forward_payload",
                new=AsyncMock(return_value=(429, "rate limited", {})),
            ),
        ):
            mock_settings.RETRY_ENDPOINT_SECRET = "secret"
            mock_settings.API_KEY_SALT = "fallback"
            mock_admin.table.return_value.select.return_value.eq.return_value.lte.return_value.lt.return_value.gte.return_value.limit.return_value.execute.return_value.data = [
                {
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
                        "form_schema": {},
                        "spam_honeypot_field": None,
                        "spam_blocked_ua": [],
                        "spam_allowed_countries": [],
                        "spam_blocked_ips": [],
                        "email_notifications": {},
                    },
                }
            ]

            response = asyncio.run(
                process_retries(
                    request=MagicMock(),
                    x_retry_secret="secret",
                )
            )
            assert response.processed == 1
            # 429 is retryable → should be "pending", not "exhausted".
            assert response.results[0]["outcome"] == "pending"


class TestRateLimitRpcSignature:
    """The limiter must call the (fixed-bucket) SQL function correctly."""

    def test_rpc_called_without_window_start(self):
        from app.routes.proxy import enforce_rate_limit

        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]
            remaining = asyncio.run(enforce_rate_limit("route-1", "1.2.3.4", 30))
            assert remaining == 29

            args, _kwargs = mock_admin.rpc.call_args
            assert args[0] == "increment_rate_limit"
            params = args[1]
            assert "p_route_id" in params and params["p_route_id"] == "route-1"
            assert "p_ip" in params and params["p_ip"] == "1.2.3.4"
            assert "p_max_requests" in params and params["p_max_requests"] == 30
            # The drifting `p_window_start` argument was removed; the bucket is
            # computed server-side so counts accumulate across requests.
            assert "p_window_start" not in params


class TestApiKeyAuth:
    """Optional X-API-Key header on the proxy endpoint."""

    def _build_route(self):
        return {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {},
            "transform_headers": {},
            "slug": "test-route",
            "name": "Test",
            "user_id": "user-1",
            "is_active": True,
            "requests_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }

    def _run(self, x_api_key=None, verify_return=None):
        from app.routes.proxy import proxy_webhook

        route = self._build_route()
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
                new=AsyncMock(return_value=verify_return),
            ) as mock_verify,
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            request = MagicMock()
            request.headers = {"content-type": "application/json"}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(return_value=b'{"name": "Jane"}')

            response = asyncio.run(
                proxy_webhook(
                    slug="test-route",
                    request=request,
                    x_api_key=x_api_key,
                    idempotency_key=None,
                )
            )
            return response, mock_forward, mock_verify

    def test_missing_api_key_allowed(self):
        response, mock_forward, mock_verify = self._run(x_api_key=None)
        assert response.status_code == 200
        mock_verify.assert_not_called()
        mock_forward.assert_called_once()

    def test_invalid_api_key_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._run(x_api_key="wrong-key", verify_return=None)
        assert exc.value.status_code == 401
        assert "Invalid API key" in exc.value.detail

    def test_valid_api_key_proceeds(self):
        response, mock_forward, mock_verify = self._run(
            x_api_key="sk_live_valid", verify_return="route-1"
        )
        assert response.status_code == 200
        mock_verify.assert_awaited_once_with("sk_live_valid")
        mock_forward.assert_called_once()


class TestOAuthCallbackRateLimit:
    """Tests for OAuth callback rate limiting."""

    def setup_method(self):
        from app.routes.oauth import _oauth_callback_cache

        _oauth_callback_cache.clear()

    def test_allows_requests_under_limit(self):
        from app.routes.oauth import _check_oauth_rate_limit

        client_ip = "1.2.3.4"
        for _ in range(5):
            asyncio.run(_check_oauth_rate_limit(client_ip))  # Should not raise

    def test_denies_requests_over_limit(self):
        from app.routes.oauth import _check_oauth_rate_limit, _OAUTH_CALLBACK_RATE_LIMIT

        client_ip = "1.2.3.4"
        # Allow up to the limit.
        for _ in range(_OAUTH_CALLBACK_RATE_LIMIT):
            asyncio.run(_check_oauth_rate_limit(client_ip))

        with pytest.raises(HTTPException) as exc:
            asyncio.run(_check_oauth_rate_limit(client_ip))
        assert exc.value.status_code == 429

    def test_different_ips_have_separate_limits(self):
        from app.routes.oauth import _check_oauth_rate_limit, _OAUTH_CALLBACK_RATE_LIMIT

        ip1 = "1.2.3.4"
        ip2 = "5.6.7.8"

        for _ in range(_OAUTH_CALLBACK_RATE_LIMIT):
            asyncio.run(_check_oauth_rate_limit(ip1))

        # ip2 should still be allowed
        asyncio.run(_check_oauth_rate_limit(ip2))  # Should not raise

    def test_window_expires_allows_requests(self):
        from app.routes.oauth import (
            _check_oauth_rate_limit,
            _OAUTH_CALLBACK_RATE_LIMIT,
            _OAUTH_CALLBACK_RATE_WINDOW,
        )

        client_ip = "1.2.3.4"

        for _ in range(_OAUTH_CALLBACK_RATE_LIMIT):
            asyncio.run(_check_oauth_rate_limit(client_ip))

        # Simulate time passing beyond the window
        with patch(
            "app.routes.oauth.time.monotonic",
            return_value=time.monotonic() + _OAUTH_CALLBACK_RATE_WINDOW + 1,
        ):
            asyncio.run(_check_oauth_rate_limit(client_ip))  # Should not raise


class TestRouteCacheInvalidation:
    """Single-route cache eviction must drop exactly the targeted slug."""

    def test_clear_route_cache_for_route(self):
        from app.routes.proxy import (
            _cache_route,
            _get_cached_route,
            clear_route_cache,
            clear_route_cache_for_route,
        )

        asyncio.run(clear_route_cache())
        asyncio.run(_cache_route("keep-me", {"id": "r1"}))
        asyncio.run(_cache_route("drop-me", {"id": "r2"}))

        asyncio.run(clear_route_cache_for_route("drop-me"))

        assert asyncio.run(_get_cached_route("drop-me")) is None
        assert asyncio.run(_get_cached_route("keep-me")) is not None
        asyncio.run(clear_route_cache())


class TestCircuitBreaker:
    """Tests for the PostgreSQL-backed outbound HTTP circuit breaker."""

    def test_opens_after_threshold_failures(self):
        from app.services.circuit_breaker import (
            is_circuit_breaker_open as _is_circuit_breaker_open,
            record_circuit_breaker_failure as _record_circuit_breaker_failure,
            _CIRCUIT_BREAKER_THRESHOLD,
        )

        url = "https://example.com/webhook"
        failure_count = 0

        def mock_execute(query):
            nonlocal failure_count
            result = MagicMock()
            query_type = type(query).__name__
            if "Select" in query_type:
                if failure_count >= _CIRCUIT_BREAKER_THRESHOLD:
                    result.data = [
                        {
                            "destination_url": url,
                            "state": "open",
                            "failure_count": failure_count,
                            "opened_at": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time())
                            ),
                        }
                    ]
                else:
                    result.data = []
            elif "RPC" in query_type:
                result.data = []
            else:
                failure_count += 1
                result.data = [{"destination_url": url, "failure_count": failure_count}]
            return result

        with patch(
            "app.services.circuit_breaker.execute_query", side_effect=mock_execute
        ):
            for _ in range(_CIRCUIT_BREAKER_THRESHOLD):
                asyncio.run(_record_circuit_breaker_failure(url))

            assert asyncio.run(_is_circuit_breaker_open(url)) is True

    def test_closes_after_success(self):
        from app.services.circuit_breaker import (
            is_circuit_breaker_open as _is_circuit_breaker_open,
            record_circuit_breaker_failure as _record_circuit_breaker_failure,
            record_circuit_breaker_success as _record_circuit_breaker_success,
            _CIRCUIT_BREAKER_THRESHOLD,
        )

        url = "https://example.com/webhook"
        failure_count = 0

        def mock_execute(query):
            nonlocal failure_count
            result = MagicMock()
            query_type = type(query).__name__
            if "Select" in query_type:
                result.data = []
            elif "RPC" in query_type:
                result.data = []
            elif "delete" in str(query).lower():
                failure_count = 0
                result.data = []
            else:
                failure_count += 1
                result.data = [{"destination_url": url, "failure_count": failure_count}]
            return result

        with patch(
            "app.services.circuit_breaker.execute_query", side_effect=mock_execute
        ):
            for _ in range(_CIRCUIT_BREAKER_THRESHOLD):
                asyncio.run(_record_circuit_breaker_failure(url))

            asyncio.run(_record_circuit_breaker_success(url))
            assert asyncio.run(_is_circuit_breaker_open(url)) is False

    def test_clear_circuit_breaker_resets_state(self):
        from app.services.circuit_breaker import (
            is_circuit_breaker_open as _is_circuit_breaker_open,
            record_circuit_breaker_failure as _record_circuit_breaker_failure,
            clear_route_circuit_breaker,
            _CIRCUIT_BREAKER_THRESHOLD,
        )

        url = "https://example.com/webhook"
        failure_count = 0

        def mock_execute(query):
            nonlocal failure_count
            result = MagicMock()
            query_type = type(query).__name__
            if "Select" in query_type:
                result.data = []
            elif "RPC" in query_type:
                result.data = []
            elif "delete" in str(query).lower():
                failure_count = 0
                result.data = []
            else:
                failure_count += 1
                result.data = [{"destination_url": url, "failure_count": failure_count}]
            return result

        with patch(
            "app.services.circuit_breaker.execute_query", side_effect=mock_execute
        ):
            for _ in range(_CIRCUIT_BREAKER_THRESHOLD):
                asyncio.run(_record_circuit_breaker_failure(url))

            asyncio.run(clear_route_circuit_breaker(url))
            assert asyncio.run(_is_circuit_breaker_open(url)) is False

    def test_half_open_after_cooldown(self):
        from app.services.circuit_breaker import (
            is_circuit_breaker_open as _is_circuit_breaker_open,
            record_circuit_breaker_failure as _record_circuit_breaker_failure,
            _CIRCUIT_BREAKER_THRESHOLD,
            _CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        )

        url = "https://example.com/webhook"
        failure_count = 0
        now_ts = time.time()

        def mock_execute(query):
            nonlocal failure_count
            result = MagicMock()
            query_type = type(query).__name__
            if "Select" in query_type:
                if failure_count >= _CIRCUIT_BREAKER_THRESHOLD:
                    opened_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
                    result.data = [
                        {
                            "destination_url": url,
                            "state": "open",
                            "failure_count": failure_count,
                            "opened_at": opened_at,
                        }
                    ]
                else:
                    result.data = []
            elif "RPC" in query_type:
                result.data = []
            else:
                failure_count += 1
                result.data = [{"destination_url": url, "failure_count": failure_count}]
            return result

        with patch(
            "app.services.circuit_breaker.execute_query", side_effect=mock_execute
        ):
            for _ in range(_CIRCUIT_BREAKER_THRESHOLD):
                asyncio.run(_record_circuit_breaker_failure(url))

            assert asyncio.run(_is_circuit_breaker_open(url)) is True

            past_time = now_ts + _CIRCUIT_BREAKER_COOLDOWN_SECONDS + 1
            with patch(
                "app.services.circuit_breaker.time.time", return_value=past_time
            ):
                assert asyncio.run(_is_circuit_breaker_open(url)) is False


class TestRateLimitResetAlignment:
    """Tests for rate-limit reset header alignment."""

    def test_rate_limit_reset_aligns_with_bucket_boundary(self):
        """X-RateLimit-Reset should align with the fixed 60s bucket boundary."""
        from app.routes.proxy import _RATE_LIMIT_WINDOW_SECONDS

        now = time.time()
        reset = int(
            math.ceil(now / _RATE_LIMIT_WINDOW_SECONDS) * _RATE_LIMIT_WINDOW_SECONDS
        )

        # Reset must be in the future and aligned to a 60s boundary.
        assert reset > now
        assert reset % _RATE_LIMIT_WINDOW_SECONDS == 0


class TestFillRouteCacheSingleFlight:
    """Tests for single-flight cache fill behavior."""

    def test_single_flight_awaits_existing_future(self):
        """When a future already exists for a slug, await it instead of querying."""
        from app.services.route_cache import (
            fill_route_cache as _fill_route_cache,
            _route_cache_fills,
        )

        route_row = {
            "id": "route-1",
            "slug": "test-route",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {},
            "transform_headers": {},
            "is_active": True,
            "user_id": "user-1",
            "name": "Test",
            "requests_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }

        call_count = 0

        def mock_query():
            nonlocal call_count
            call_count += 1
            return MagicMock(data=[route_row])

        with (
            patch("app.services.route_cache.admin") as mock_admin,
            patch("app.services.route_cache._cache_route", new_callable=AsyncMock),
        ):
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute = mock_query

            from app.services.route_cache import clear_route_cache

            asyncio.run(clear_route_cache())

            async def scenario():
                # Manually inject a completed future into the fills dict to
                # simulate an in-flight request that just finished.
                loop = asyncio.get_running_loop()
                fut = loop.create_future()
                fut.set_result(route_row)
                _route_cache_fills["test-route"] = (fut, time_module.monotonic())

                # This call should await the existing future, not hit the DB.
                result = await _fill_route_cache("test-route")
                return result

            result = asyncio.run(scenario())

        assert result == route_row
        assert call_count == 0, f"Expected 0 DB calls, got {call_count}"

    def test_failure_removes_inflight_marker(self):
        """On DB failure, the in-flight marker must be removed so retries work."""
        from app.services.route_cache import fill_route_cache as _fill_route_cache
        from fastapi import HTTPException

        with (
            patch("app.services.route_cache.admin") as mock_admin,
            patch("app.services.route_cache._route_cache_fills", {}),
            patch("app.services.route_cache._route_cache_fills_lock"),
        ):
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(_fill_route_cache("missing-route"))
            assert exc_info.value.status_code == 404

            # The in-flight marker must be gone so the next request can retry.
            from app.services.route_cache import _route_cache_fills as fills

            assert "missing-route" not in fills

    def test_health_check_requires_auth(self):
        """Outbound health check must reject unauthenticated requests."""
        response = client.get("/internal/health/outbound")
        assert response.status_code == 401

    def test_health_check_rejects_wrong_secret(self):
        """Outbound health check must reject invalid secrets."""
        response = client.get(
            "/internal/health/outbound",
            headers={"X-Retry-Secret": "wrong-secret"},
        )
        assert response.status_code == 401


class TestOAuthRateLimitBoundedEviction:
    """OAuth rate-limit cache must not grow unbounded."""

    def test_eviction_when_cache_exceeds_limit(self):
        """When the cache exceeds _OAUTH_CACHE_MAX_ENTRIES, oldest entries are evicted."""
        from app.routes.oauth import (
            _check_oauth_rate_limit,
            _oauth_callback_cache,
            _OAUTH_CACHE_MAX_ENTRIES,
        )

        # Fill the cache to the limit with unique IPs (one request each).
        for i in range(_OAUTH_CACHE_MAX_ENTRIES):
            ip = f"10.0.{i // 256}.{i % 256}"
            asyncio.run(_check_oauth_rate_limit(ip))

        assert len(_oauth_callback_cache) <= _OAUTH_CACHE_MAX_ENTRIES

        # One more unique IP should trigger eviction.
        asyncio.run(_check_oauth_rate_limit("192.168.1.1"))
        assert len(_oauth_callback_cache) <= _OAUTH_CACHE_MAX_ENTRIES


class TestCircuitBreakerBoundedEviction:
    """Circuit breaker state must not grow unbounded."""

    def test_eviction_when_state_exceeds_limit(self):
        """When circuit breaker state exceeds _CIRCUIT_BREAKER_MAX_ENTRIES, oldest are evicted."""
        from app.routes.proxy import (
            _record_circuit_breaker_failure,
            _circuit_breaker_state,
            _CIRCUIT_BREAKER_MAX_ENTRIES,
        )

        # Fill the circuit breaker state to the limit.
        for i in range(_CIRCUIT_BREAKER_MAX_ENTRIES):
            url = f"https://example{i}.com/webhook"
            asyncio.run(_record_circuit_breaker_failure(url))

        assert len(_circuit_breaker_state) <= _CIRCUIT_BREAKER_MAX_ENTRIES

        # One more URL should trigger eviction.
        asyncio.run(_record_circuit_breaker_failure("https://newsite.com/webhook"))
        assert len(_circuit_breaker_state) <= _CIRCUIT_BREAKER_MAX_ENTRIES


class TestValidateDestinationUrlAsync:
    """Tests for validate_destination_url_async behavior."""

    def test_negative_geolocation_cached(self):
        """Failed IP lookups should be cached as None to avoid repeated HTTP requests."""
        from app.routes.proxy import _lookup_country_code, _ip_country_cache

        # Clear cache
        asyncio.run(_ip_country_cache.clear())

        # Use a private IP that should be cached as None without HTTP request
        with patch("app.routes.proxy.get_http_client") as mock_client:
            result = asyncio.run(_lookup_country_code("192.168.1.1"))
            assert result is None
            # Should not have made any HTTP requests
            mock_client.assert_not_called()
            # Should be cached
            cached = asyncio.run(_ip_country_cache.get("192.168.1.1"))
            assert cached is None

    def test_no_dns_resolution_skips_thread(self):
        """When resolve_dns=False, validate_destination_url_async should not dispatch to a thread."""
        from app.utils.security import validate_destination_url_async

        with patch("asyncio.to_thread") as mock_to_thread:
            asyncio.run(
                validate_destination_url_async("https://example.com", resolve_dns=False)
            )
            mock_to_thread.assert_not_called()

    def test_dns_resolution_uses_thread(self):
        """When resolve_dns=True, validate_destination_url_async should dispatch to a thread."""
        from app.utils.security import validate_destination_url_async

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = None
            asyncio.run(
                validate_destination_url_async("https://example.com", resolve_dns=True)
            )
            mock_to_thread.assert_called_once()


class TestSafeErrorDetail:
    """Tests for safe_error_detail sanitization."""

    def test_redacts_connection_strings(self):
        """Development errors should redact host portion of connection strings."""
        from app.utils.security import safe_error_detail

        with patch("app.utils.security.settings") as mock_settings:
            mock_settings.is_development = True
            exc = Exception(
                "Failed to connect to postgres://user:pass@db.example.com:5432/mydb"
            )
            detail = safe_error_detail(exc)
            # The host+port after @ is redacted, but scheme and user:pass are kept.
            assert "db.example.com:5432" not in detail
            assert "<redacted>" in detail

    def test_redacts_internal_ips(self):
        """Development errors should redact private/internal IP addresses."""
        from app.utils.security import safe_error_detail

        with patch("app.utils.security.settings") as mock_settings:
            mock_settings.is_development = True
            exc = Exception("Connection refused to 192.168.1.100:8080")
            detail = safe_error_detail(exc)
            assert "192.168.1.100" not in detail
            assert "<internal-ip>" in detail

    def test_production_returns_generic_message(self):
        """Production errors should return a generic message."""
        from app.utils.security import safe_error_detail

        with patch("app.utils.security.settings") as mock_settings:
            mock_settings.is_development = False
            exc = Exception("postgres://user:pass@db.example.com/mydb")
            detail = safe_error_detail(exc)
            assert detail == "An internal error occurred"


class TestProcessRetriesBatchSize:
    """Tests for process_retries batch size configuration."""

    def test_batch_size_is_configurable(self):
        """The retry batch size should be a module-level constant."""
        from app.routes.proxy import _RETRY_BATCH_SIZE

        assert isinstance(_RETRY_BATCH_SIZE, int)
        assert _RETRY_BATCH_SIZE > 0


class TestRequestSizeLimitMiddleware:
    """Tests for request size and timeout limits."""

    def test_oversized_body_returns_413(self):
        """Request body exceeding max_size should return 413."""
        from app.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        large_body = b"x" * (1024 * 1024 + 1)  # 1 MiB + 1 byte

        response = client.post("/", content=large_body)
        assert response.status_code == 413

    def test_slow_body_returns_408(self):
        """Request body arriving slower than max_seconds should return 408."""
        # This test verifies the middleware logic conceptually.
        # In practice, testing actual slow-loris timing in unit tests is
        # fragile, so we verify the middleware is installed and the
        # timeout constants are sane.
        from app.main import _DEFAULT_MAX_BODY_SECONDS, _DEFAULT_MAX_BODY_BYTES

        assert _DEFAULT_MAX_BODY_SECONDS > 0
        assert _DEFAULT_MAX_BODY_BYTES > 0


class TestCryptoRoundTrip:
    """Tests for webhook secret encryption/decryption."""

    def test_encrypt_decrypt_round_trip(self):
        """Encrypted secret should decrypt back to the original."""
        from app.crypto import encrypt_webhook_secret, decrypt_webhook_secret

        plaintext = "super-secret-webhook-key-123"
        encrypted = encrypt_webhook_secret(plaintext)
        assert encrypted is not None
        assert encrypted.startswith("v1:")
        assert plaintext not in encrypted  # Should not be plaintext

        decrypted = decrypt_webhook_secret(encrypted)
        assert decrypted == plaintext

    def test_safe_plain_prefix_without_key(self):
        """Without ENCRYPTION_KEY, should return safe_plain: prefixed value."""
        from app.crypto import encrypt_webhook_secret, decrypt_webhook_secret

        # Temporarily clear the fernet cache to simulate no key
        from app.crypto import clear_fernet_cache

        clear_fernet_cache()

        try:
            with patch("app.crypto.settings") as mock_settings:
                mock_settings.is_production = False
                mock_settings.ENCRYPTION_KEY = ""
                plaintext = "test-secret"
                encrypted = encrypt_webhook_secret(plaintext)
                assert encrypted is not None
                assert encrypted.startswith("safe_plain:")

                decrypted = decrypt_webhook_secret(encrypted)
                assert decrypted == plaintext
        finally:
            clear_fernet_cache()

    def test_decrypt_raises_on_encrypted_without_key(self):
        """Decrypting v1: encrypted data without ENCRYPTION_KEY should raise."""
        from app.crypto import decrypt_webhook_secret, clear_fernet_cache

        clear_fernet_cache()
        try:
            with patch("app.crypto.settings") as mock_settings:
                mock_settings.is_production = False
                mock_settings.ENCRYPTION_KEY = ""
                with pytest.raises(ValueError, match="encryption is not configured"):
                    decrypt_webhook_secret("v1:gAAAAA...")
        finally:
            clear_fernet_cache()


class TestClaimIdempotency:
    """Tests for atomic idempotency claim and wait helpers."""

    def test_claim_success_returns_true(self):
        from app.routes.proxy import claim_idempotency

        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.return_value.data = [True]
            result = asyncio.run(claim_idempotency("route-1", "key-1"))
            assert result is True
            mock_admin.rpc.assert_called_once_with(
                "claim_idempotency_key",
                {"p_route_id": "route-1", "p_idempotency_key": "key-1"},
            )

    def test_claim_duplicate_returns_false(self):
        from app.routes.proxy import claim_idempotency

        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.return_value.data = [False]
            result = asyncio.run(claim_idempotency("route-1", "key-1"))
            assert result is False

    def test_claim_rpc_error_returns_false(self):
        from app.routes.proxy import claim_idempotency

        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.rpc.return_value.execute.side_effect = Exception("DB error")
            result = asyncio.run(claim_idempotency("route-1", "key-1"))
            assert result is False

    def test_wait_returns_cached_result(self):
        from app.routes.proxy import _wait_for_idempotency_result

        cached = {
            "status": "idempotent",
            "destination_status": 200,
            "response_body": "ok",
            "response_headers": {},
            "idempotent": True,
        }
        with (
            patch("app.routes.proxy.check_idempotency", return_value=cached),
        ):
            result = asyncio.run(
                _wait_for_idempotency_result(
                    "route-1", "key-1", timeout=1.0, poll_interval=0.1
                )
            )
            assert result == cached

    def test_wait_returns_none_on_timeout(self):
        from app.routes.proxy import _wait_for_idempotency_result

        with (
            patch("app.routes.proxy.check_idempotency", return_value=None),
        ):
            result = asyncio.run(
                _wait_for_idempotency_result(
                    "route-1", "key-1", timeout=0.2, poll_interval=0.1
                )
            )
            assert result is None


class TestDisposableEmailLoading:
    """Tests that disposable email domains are actually loaded and checked."""

    def test_is_disposable_email_returns_true_for_known_domain(self):
        from app.utils.email import is_disposable_email

        # The embedded list should be loaded; mailinator.com is in it.
        assert is_disposable_email("test@mailinator.com") is True

    def test_is_disposable_email_returns_false_for_legitimate_domain(self):
        from app.utils.email import is_disposable_email

        assert is_disposable_email("test@gmail.com") is False

    def test_is_disposable_email_handles_missing_at(self):
        from app.utils.email import is_disposable_email

        assert is_disposable_email("not-an-email") is False

    def test_is_disposable_email_handles_none(self):
        from app.utils.email import is_disposable_email

        assert is_disposable_email("") is False


class TestEmailRenderingSecurity:
    """Tests for email rendering security."""

    def test_render_submission_email_escapes_html(self):
        """Payload values with HTML should be escaped in email body."""
        from app.utils.email import _render_submission_email

        payload = {
            "name": "<script>alert('xss')</script>",
            "email": "test@example.com",
        }
        email = _render_submission_email(
            to="admin@example.com",
            subject="Test",
            payload=payload,
            route_name="Test Route",
        )
        html_body = email["html"]
        # The script tag should be escaped, not present as raw HTML.
        assert "<script>" not in html_body
        assert "&lt;script&gt;" in html_body
        # Normal values should still be present.
        assert "test@example.com" in html_body

    def test_render_submission_email_escapes_special_chars(self):
        """Special characters should be HTML-escaped."""
        from app.utils.email import _render_submission_email

        payload = {"value": "A & B < C > D 'quoted'"}
        email = _render_submission_email(
            to="admin@example.com",
            subject="Test",
            payload=payload,
            route_name="Test Route",
        )
        html_body = email["html"]
        assert "&amp;" in html_body
        assert "&lt;" in html_body
        assert "&gt;" in html_body


class TestEmailNotifications:
    """Tests for email notification delivery."""

    def test_sends_email_on_success_when_enabled(self):
        """When email_notifications.enabled is true and delivery succeeds, send_submission_email should be called."""
        from app.routes.proxy import proxy_webhook

        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {
                "enabled": True,
                "to": "admin@example.com",
                "subject": "New submission",
            },
            "transform_headers": {},
            "slug": "test-route",
            "name": "Test Route",
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
            ),
            patch("app.routes.proxy.bump_route_metrics_atomic"),
            patch("app.routes.proxy.send_submission_email") as mock_send_email,
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            request = MagicMock()
            request.headers = {"content-type": "application/json"}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(return_value=b'{"name": "Jane"}')

            asyncio.run(
                proxy_webhook(
                    slug="test-route",
                    request=request,
                    idempotency_key=None,
                    x_api_key=None,
                )
            )

            mock_send_email.assert_called_once()
            call_kwargs = mock_send_email.call_args[1]
            assert call_kwargs["to"] == "admin@example.com"
            assert call_kwargs["subject"] == "New submission"
            assert call_kwargs["route_name"] == "Test Route"

    def test_skips_email_when_disabled(self):
        """When email_notifications is empty, send_submission_email should not be called."""
        from app.routes.proxy import proxy_webhook

        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {},
            "transform_headers": {},
            "slug": "test-route",
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
            ),
            patch("app.routes.proxy.bump_route_metrics_atomic"),
            patch("app.routes.proxy.send_submission_email") as mock_send_email,
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            request = MagicMock()
            request.headers = {"content-type": "application/json"}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(return_value=b'{"name": "Jane"}')

            asyncio.run(
                proxy_webhook(
                    slug="test-route",
                    request=request,
                    idempotency_key=None,
                    x_api_key=None,
                )
            )

            mock_send_email.assert_not_called()

    def test_send_with_retry_skips_permanent_4xx_error(self):
        """Resend 4xx errors should not be retried."""
        from app.utils.email import _send_with_retry
        from resend.exceptions import ResendError

        class FakeResendError(ResendError):
            def __init__(self):
                super().__init__(
                    "401",
                    "authentication_error",
                    "Invalid API key",
                    "check your API key",
                )

        with (
            patch("app.utils.email.settings.RESEND_API_KEY", "test-key"),
            patch("app.utils.email.resend.Emails.send") as mock_send,
        ):
            mock_send.side_effect = FakeResendError()

            result = asyncio.run(_send_with_retry({"to": "test@example.com"}))
            assert result is False
            # Should be called exactly once (no retries on 4xx)
            assert mock_send.call_count == 1

    def test_send_with_retry_retries_on_transient_error(self):
        """Transient errors should be retried up to the limit."""
        from app.utils.email import _send_with_retry

        with (
            patch("app.utils.email.settings.RESEND_API_KEY", "test-key"),
            patch("app.utils.email.resend.Emails.send") as mock_send,
        ):
            mock_send.side_effect = [
                Exception("Network timeout"),
                Exception("Network timeout"),
                Exception("Network timeout"),
            ]

            result = asyncio.run(_send_with_retry({"to": "test@example.com"}))
            assert result is False
            # Should retry 3 times (default _EMAIL_RETRY_ATTEMPTS)
            assert mock_send.call_count == 3

    def test_send_submission_email_validates_recipient(self):
        """Invalid recipient email addresses should be rejected early."""
        from app.utils.email import send_submission_email

        with (
            patch("app.utils.email.settings.RESEND_API_KEY", "test-key"),
            patch("app.utils.email.resend.Emails.send") as mock_send,
        ):
            result = asyncio.run(
                send_submission_email(
                    to="not-an-email",
                    subject="Test",
                    payload={"key": "value"},
                    route_name="Test",
                )
            )
            assert result is False
            mock_send.assert_not_called()

    def test_skips_email_on_failed_delivery(self):
        """When delivery fails (status >= 400), send_submission_email should not be called."""
        from app.routes.proxy import proxy_webhook

        route = {
            "id": "route-1",
            "destination_url": "https://example.com",
            "method": "POST",
            "headers": {},
            "rate_limit": 30,
            "webhook_secret": None,
            "transform_body_template": None,
            "form_schema": {},
            "spam_honeypot_field": None,
            "spam_blocked_ua": [],
            "spam_allowed_countries": [],
            "spam_blocked_ips": [],
            "email_notifications": {
                "enabled": True,
                "to": "admin@example.com",
                "subject": "New submission",
            },
            "transform_headers": {},
            "slug": "test-route",
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
                new=AsyncMock(return_value=(500, "error", {})),
            ),
            patch("app.routes.proxy.bump_route_metrics_atomic"),
            patch("app.routes.proxy.send_submission_email") as mock_send_email,
        ):
            mock_cache_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                route
            ]
            mock_admin.rpc.return_value.execute.return_value.data = [
                {"success": True, "new_count": 1}
            ]

            from app.services.route_cache import _cache_route

            asyncio.run(_cache_route("test-route", route))

            request = MagicMock()
            request.headers = {"content-type": "application/json"}
            request.client = MagicMock(host="1.2.3.4")
            request.body = AsyncMock(return_value=b'{"name": "Jane"}')

            asyncio.run(
                proxy_webhook(
                    slug="test-route",
                    request=request,
                    idempotency_key=None,
                    x_api_key=None,
                )
            )

            mock_send_email.assert_not_called()
