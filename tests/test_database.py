"""Tests for database helper functions (API key generation and verification)."""

import asyncio
from unittest.mock import patch

from app.database import (
    generate_api_key,
    verify_api_key,
    _hash_api_key,
    has_http_client,
)


class TestGenerateApiKey:
    """Tests for API key generation."""

    def test_returns_three_parts(self):
        full_key, prefix, key_hash = generate_api_key()
        assert isinstance(full_key, str)
        assert isinstance(prefix, str)
        assert isinstance(key_hash, str)

    def test_key_starts_with_prefix(self):
        full_key, prefix, _ = generate_api_key()
        assert full_key.startswith("sk_live_")
        assert prefix == full_key[:12]

    def test_hash_is_not_empty(self):
        _, _, key_hash = generate_api_key()
        assert len(key_hash) > 0

    def test_unique_keys(self):
        keys = {generate_api_key()[0] for _ in range(10)}
        assert len(keys) == 10, "All generated keys should be unique"

    def test_hash_is_deterministic(self):
        """Same key should always produce the same hash."""
        full_key, _, hash1 = generate_api_key()
        # Manually verify by re-hashing.
        hash2 = _hash_api_key(full_key)
        assert hash1 == hash2

    def test_hash_api_key_produces_hex_string(self):
        """_hash_api_key should return a 64-char hex string."""
        result = _hash_api_key("test-key")
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_api_key_depends_on_salt(self):
        """Different salts should produce different hashes."""
        with patch("app.database.settings") as mock_settings:
            mock_settings.API_KEY_SALT = "salt-one"
            hash1 = _hash_api_key("key")
        with patch("app.database.settings") as mock_settings:
            mock_settings.API_KEY_SALT = "salt-two"
            hash2 = _hash_api_key("key")
        assert hash1 != hash2


class TestHasHttpClient:
    """Tests for HTTP client availability check."""

    def test_returns_false_when_no_client(self):
        from app.database import _http_client

        original = _http_client
        try:
            import app.database as db_mod

            db_mod._http_client = None
            assert has_http_client() is False
        finally:
            db_mod._http_client = original


class TestVerifyApiKey:
    """Tests for API key verification (requires Supabase for full test)."""

    def test_none_key_returns_none(self):
        result = asyncio.run(verify_api_key(None))
        assert result is None

    def test_empty_key_returns_none(self):
        result = asyncio.run(verify_api_key(""))
        assert result is None
