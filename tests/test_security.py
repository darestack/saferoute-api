"""Tests for security utilities (SSRF guard, slug, client IP, error redaction)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import Request

from app.config import settings
from app.utils.security import (
    generate_slug,
    get_client_ip,
    safe_error_detail,
    validate_destination_url,
    verify_webhook_signature,
)


class TestValidateDestinationUrl:
    """SSRF guardrail behaviour (no live DNS; socket patched)."""

    def test_accepts_public_https(self):
        # A literal public IP passes the DNS-free request-time check. We patch
        # _is_public_ip to avoid depending on a live public IP address.
        with patch("app.utils.security._is_public_ip", return_value=True):
            validate_destination_url("https://8.8.8.8/hook", resolve_dns=False)

    def test_rejects_http_scheme(self):
        with pytest.raises(ValueError, match="HTTPS"):
            validate_destination_url("http://example.com/hook")

    def test_rejects_credentials_in_url(self):
        with pytest.raises(ValueError, match="credentials"):
            validate_destination_url("https://user:pass@example.com/hook")

    def test_rejects_localhost_at_write_time(self):
        # At request time (resolve_dns=False) localhost is allowed because the
        # SSRF guard defers full resolution; the write-time check (resolve_dns
        # = True) must reject it. Verify the write-time path rejects it.
        import socket

        with patch(
            "app.utils.security.socket.getaddrinfo",
            side_effect=socket.gaierror("no resolution"),
        ):
            with pytest.raises(ValueError):
                validate_destination_url("https://localhost/hook", resolve_dns=True)

    def test_rejects_private_ip_literal(self):
        with pytest.raises(ValueError):
            validate_destination_url("https://10.0.0.1/hook", resolve_dns=False)

    def test_rejects_non_public_dns_resolution(self):
        # 127.0.0.1 is loopback -> not public.
        with patch(
            "app.utils.security.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("127.0.0.1", 443))],
        ):
            with pytest.raises(ValueError, match="public"):
                validate_destination_url("https://internal.example.com/hook")

    def test_rejects_unresolvable_host(self):
        import socket

        with patch(
            "app.utils.security.socket.getaddrinfo",
            side_effect=socket.gaierror("no resolution"),
        ):
            with pytest.raises(ValueError, match="resolved"):
                validate_destination_url("https://nope.invalid/hook")

    def test_resolve_dns_false_allows_hostname(self):
        # Without DNS resolution, a hostname with no literal IP is accepted
        # (cheap request-time check only; full check happens at write time).
        validate_destination_url("https://api.example.com/hook", resolve_dns=False)


class TestGenerateSlug:
    """Slug generation invariants."""

    def test_slug_is_lowercase_and_hyphenated(self):
        slug = generate_slug("My Cool Route!")
        assert slug == slug.lower()
        assert " " not in slug

    def test_slug_has_random_suffix(self):
        a = generate_slug("Route")
        b = generate_slug("Route")
        assert a != b
        assert a.endswith(a.split("-")[-1]) and len(a.split("-")[-1]) == 12

    def test_slug_strips_invalid_chars(self):
        slug = generate_slug("route with/slash and#hash")
        assert "/" not in slug and "#" not in slug

    def test_slug_without_name_falls_back(self):
        slug = generate_slug("!!!")
        assert slug.startswith("route-")


class TestVerifyWebhookSignature:
    """HMAC signature verification."""

    def test_valid_signature_passes(self):
        import hmac

        body = b'{"a":1}'
        secret = "topsecret"
        expected = "sha256=" + hmac.new(secret.encode(), body, "sha256").hexdigest()
        assert verify_webhook_signature(body, expected, secret) is True

    def test_wrong_secret_fails(self):
        import hmac

        body = b'{"a":1}'
        expected = "sha256=" + hmac.new(b"other", body, "sha256").hexdigest()
        assert verify_webhook_signature(body, expected, "topsecret") is False

    def test_missing_secret_and_signature_is_ok(self):
        # No verification required when neither is present.
        assert verify_webhook_signature(b"x", None, "") is True

    def test_missing_secret_with_signature_fails(self):
        assert verify_webhook_signature(b"x", "sha256=abc", "") is False


class TestGetClientIp:
    """Client IP extraction with trusted-proxy handling."""

    def _request(self, headers: dict, client_host: str) -> Request:
        scope = {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("127.0.0.1" if client_host == "loopback" else client_host, 1234),
        }
        return Request(scope)

    def test_direct_client_used_when_no_forwarded(self):
        req = self._request({}, "198.51.100.7")
        assert get_client_ip(req) == "198.51.100.7"

    def test_untrusted_proxy_ignores_xff(self):
        req = self._request({"X-Forwarded-For": "198.51.100.7"}, "203.0.113.5")
        # Peer not in TRUSTED_PROXIES -> XFF ignored, direct peer returned.
        assert get_client_ip(req) == "203.0.113.5"

    def test_trusted_proxy_uses_rightmost_xff(self):
        with patch.object(settings, "TRUSTED_PROXIES", "203.0.113.5"):
            req = self._request(
                {"X-Forwarded-For": "10.0.0.1, 198.51.100.7"}, "203.0.113.5"
            )
            assert get_client_ip(req) == "198.51.100.7"

    def test_unknown_client_returns_unknown(self):
        scope = {"type": "http", "headers": [], "client": None}
        assert get_client_ip(Request(scope)) == "unknown"


class TestSafeErrorDetail:
    """Error detail redaction in development mode."""

    def test_production_returns_generic(self):
        with patch.object(settings, "ENVIRONMENT", "production"):
            assert safe_error_detail(RuntimeError("db password leaked")) == (
                "An internal error occurred"
            )

    def test_development_redacts_connection_string(self):
        with patch.object(settings, "ENVIRONMENT", "development"):
            msg = safe_error_detail(RuntimeError("postgres://user:pass@db.host/x"))
            assert "pass@db.host" not in msg
            assert "<redacted>" in msg

    def test_development_redacts_internal_ip(self):
        with patch.object(settings, "ENVIRONMENT", "development"):
            msg = safe_error_detail(RuntimeError("connect to 10.0.0.5 failed"))
            assert "10.0.0.5" not in msg
            assert "<internal-ip>" in msg
