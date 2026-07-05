"""Tests for proxy helper functions (no Supabase dependency)."""

import asyncio
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch


from app.routes.proxy import (
    get_client_ip,
    parse_payload,
    resolve_dot_path,
    render_template,
    verify_webhook_signature,
    _should_retry,
    _calculate_next_retry,
)


class TestGetClientIp:
    """Tests for client IP extraction."""

    def test_x_forwarded_for_single(self):
        class FakeRequest:
            headers = {"X-Forwarded-For": "1.2.3.4"}
            client = None

        assert get_client_ip(FakeRequest()) == "1.2.3.4"

    def test_x_forwarded_for_chain(self):
        class FakeRequest:
            headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8, 9.10.11.12"}
            client = None

        assert get_client_ip(FakeRequest()) == "1.2.3.4"

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
        return hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()

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


class TestShouldRetry:
    """Tests for retry logic."""

    def test_reversible_5xx_should_retry(self):
        assert _should_retry(502) is True
        assert _should_retry(503) is True
        assert _should_retry(504) is True

    def test_non_retryable_5xx_should_not_retry(self):
        assert _should_retry(500) is False
        assert _should_retry(501) is False
        assert _should_retry(505) is False
        assert _should_retry(507) is False

    def test_2xx_should_not_retry(self):
        assert _should_retry(200) is False
        assert _should_retry(201) is False

    def test_4xx_should_not_retry(self):
        assert _should_retry(400) is False
        assert _should_retry(404) is False
        assert _should_retry(429) is False


class TestCalculateNextRetry:
    """Tests for exponential backoff calculation."""

    def test_first_retry(self):
        result = _calculate_next_retry(0)
        assert isinstance(result, str)
        assert "T" in result  # ISO format

    def test_increasing_delay(self):
        r0 = _calculate_next_retry(0)
        r1 = _calculate_next_retry(1)
        r2 = _calculate_next_retry(2)
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
            result = check_idempotency("route-1", "key-1")
            assert result is not None
            assert result["destination_status"] == 200
            assert result["response_body"] == "ok"
            assert result["response_headers"] == {"X-Custom": "v"}

    def test_store_persists_headers(self):
        from app.routes.proxy import store_idempotency

        with patch("app.routes.proxy.admin") as mock_admin:
            store_idempotency("route-1", "key-1", 200, "ok", {"X": "v"})
            call_args = mock_admin.table.return_value.upsert.call_args
            record = call_args[0][0] if call_args[0] else call_args[1]["record"]
            assert record["response_headers"] == {"X": "v"}
            assert record["response_body"] == "ok"


class TestLogDeliveryContentType:
    """Tests that log_delivery persists content_type."""

    def test_content_type_stored(self):
        from app.routes.proxy import log_delivery

        with patch("app.routes.proxy.admin") as mock_admin:
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
            call_args = mock_admin.table.return_value.insert.call_args
            record = call_args[0][0] if call_args[0] else call_args[1]["record"]
            assert record["content_type"] == "application/json"


class TestProcessRetriesEmptyDestination:
    """Tests retry endpoint skips routes with empty destination URLs."""

    def test_marks_exhausted_when_no_destination(self):
        from app.routes.proxy import process_retries

        with patch("app.routes.proxy.admin") as mock_admin, \
             patch("app.routes.proxy.settings") as mock_settings:
            mock_settings.RETRY_ENDPOINT_SECRET = "secret"
            mock_settings.API_KEY_SALT = "fallback"
            mock_admin.table.return_value.select.return_value.eq.return_value.lte.return_value.lt.return_value.limit.return_value.execute.return_value.data = [
                {
                    "id": 1,
                    "retry_count": 0,
                    "routes": {"destination_url": "", "method": "POST", "headers": {}, "transform_headers": {}, "transform_body_template": None},
                }
            ]

            response = asyncio.run(process_retries(
                request=MagicMock(),
                x_retry_secret="secret",
            ))
            assert response["processed"] == 1
            assert response["results"][0]["outcome"] == "exhausted"
