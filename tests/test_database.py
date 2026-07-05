"""Tests for database helper functions (API key generation and verification)."""

from app.database import generate_api_key, verify_api_key


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
        from app.database import _hash_api_key
        hash2 = _hash_api_key(full_key)
        assert hash1 == hash2


class TestVerifyApiKey:
    """Tests for API key verification (requires Supabase for full test)."""

    def test_none_key_returns_none(self):
        result = verify_api_key(None)
        assert result is None

    def test_empty_key_returns_none(self):
        result = verify_api_key("")
        assert result is None
