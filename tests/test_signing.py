"""Tests for response signing utilities."""

from __future__ import annotations


from app.utils.signing import get_signature_header, sign_response, verify_response_signature


class TestSignResponse:
    """Tests for response signing."""

    def test_sign_response_consistent(self):
        body = b"test body"
        secret = "secret123"
        sig1 = sign_response(body, secret)
        sig2 = sign_response(body, secret)
        assert sig1 == sig2
        assert len(sig1) == 64  # SHA256 hex length

    def test_sign_response_different_secrets(self):
        body = b"test body"
        sig1 = sign_response(body, "secret1")
        sig2 = sign_response(body, "secret2")
        assert sig1 != sig2

    def test_sign_response_different_bodies(self):
        secret = "secret123"
        sig1 = sign_response(b"body1", secret)
        sig2 = sign_response(b"body2", secret)
        assert sig1 != sig2


class TestVerifyResponseSignature:
    """Tests for response signature verification."""

    def test_verify_valid_signature(self):
        body = b"test body"
        secret = "secret123"
        sig = sign_response(body, secret)
        assert verify_response_signature(body, sig, secret) is True

    def test_verify_invalid_signature(self):
        body = b"test body"
        secret = "secret123"
        assert verify_response_signature(body, "invalidsig", secret) is False

    def test_verify_wrong_secret(self):
        body = b"test body"
        sig = sign_response(body, "secret1")
        assert verify_response_signature(body, sig, "secret2") is False

    def test_verify_timing_safe(self):
        body = b"test body"
        secret = "secret123"
        # Should not raise even with wrong signature
        assert verify_response_signature(body, "a" * 64, secret) is False


class TestGetSignatureHeader:
    """Tests for signature header formatting."""

    def test_format(self):
        assert get_signature_header("abc123") == "sha256=abc123"
