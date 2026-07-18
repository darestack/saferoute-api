"""Tests for PKCE utilities."""

from __future__ import annotations

import base64
import hashlib

import pytest

from app.utils.pkce import generate_pkce_pair


class TestGeneratePkcePair:
    """Tests for PKCE pair generation."""

    def test_returns_tuple_of_strings(self):
        """Should return a tuple of two strings."""
        verifier, challenge = generate_pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

    def test_code_verifier_length(self):
        """Code verifier should be approximately 64 characters."""
        verifier, _ = generate_pkce_pair()
        # token_urlsafe with 64 bytes produces ~86 chars
        assert len(verifier) >= 64

    def test_code_challenge_is_base64url(self):
        """Code challenge should be base64url encoded SHA256 hash."""
        verifier, challenge = generate_pkce_pair()
        # Verify the challenge is correct
        hashed = hashlib.sha256(verifier.encode("utf-8")).digest()
        expected = base64.urlsafe_b64encode(hashed).rstrip(b"=").decode("utf-8")
        assert challenge == expected

    def test_different_calls_produce_different_values(self):
        """Each call should produce unique values."""
        pair1 = generate_pkce_pair()
        pair2 = generate_pkce_pair()
        assert pair1 != pair2

    def test_code_challenge_has_no_padding(self):
        """Code challenge should not have base64 padding."""
        _, challenge = generate_pkce_pair()
        assert "=" not in challenge
