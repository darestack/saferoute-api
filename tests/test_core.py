"""Tests for SafeRoute API core helpers."""

import hashlib
import hmac
import secrets
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

from app.config import Settings
from app.database import generate_api_key, verify_api_key
from app.routes.proxy import parse_payload, get_client_ip


class TestGenerateApiKey:
    def test_returns_three_values(self):
        full_key, prefix, key_hash = generate_api_key()
        assert isinstance(full_key, str)
        assert isinstance(prefix, str)
        assert isinstance(key_hash, str)

    def test_full_key_has_correct_prefix(self):
        full_key, _, _ = generate_api_key()
        assert full_key.startswith("sk_live_")

    def test_prefix_is_first_twelve_chars(self):
        full_key, prefix, _ = generate_api_key()
        assert prefix == full_key[:12]

    def test_key_hash_is_sha256_hex(self):
        full_key, _, key_hash = generate_api_key()
        expected = hmac.new(
            Settings().API_KEY_SALT.encode(),
            full_key.encode(),
            hashlib.sha256,
        ).hexdigest()
        assert key_hash == expected
        assert len(key_hash) == 64

    def test_keys_are_unique(self):
        key1 = generate_api_key()
        key2 = generate_api_key()
        assert key1[0] != key2[0]


class TestVerifyApiKey:
    def test_returns_none_for_invalid_key(self):
        assert verify_api_key("sk_live_doesnotexist") is None

    def test_returns_route_id_for_valid_key(self):
        _, prefix, key_hash = generate_api_key()
        fake_route_id = "123e4567-e89b-12d3-a456-426614174000"
        mock_result = MagicMock()
        mock_result.data = [{"id": fake_route_id}]
        with patch("app.database.admin") as mock_admin:
            mock_admin.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result
            assert verify_api_key("sk_live_fakekey1234567890") == fake_route_id


class TestParsePayload:
    def test_empty_body_returns_empty_dict(self):
        assert parse_payload(b"", "") == {}

    def test_json_body_parsed(self):
        body = b'{"name": "Alice", "email": "alice@example.com"}'
        result = parse_payload(body, "application/json")
        assert result["name"] == "Alice"
        assert result["email"] == "alice@example.com"

    def test_form_body_parsed(self):
        body = b"name=Alice&email=alice%40example.com"
        result = parse_payload(body, "application/x-www-form-urlencoded")
        assert result["name"] == "Alice"
        assert result["email"] == "alice@example.com"

    def test_invalid_json_returns_empty_dict(self):
        body = b"not json"
        result = parse_payload(body, "application/json")
        assert result == {}

    def test_none_body_returns_empty_dict(self):
        assert parse_payload(None, "application/json") == {}


class TestGetClientIp:
    def test_x_forwarded_for_used_when_present(self):
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        request.client = None
        assert get_client_ip(request) == "1.2.3.4"

    def test_falls_back_to_client_host(self):
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock(host="9.9.9.9")
        assert get_client_ip(request) == "9.9.9.9"

    def test_returns_unknown_when_no_ip_available(self):
        request = MagicMock()
        request.headers = {}
        request.client = None
        assert get_client_ip(request) == "unknown"
