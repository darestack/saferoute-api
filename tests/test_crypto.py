"""Tests for webhook secret encryption and decryption."""

import base64
from unittest.mock import patch

from app.crypto import decrypt_webhook_secret, encrypt_webhook_secret, _derive_key


class TestEncryptDecryptWebhookSecret:
    """Tests for webhook secret encryption/decryption."""

    def test_encrypt_returns_string(self):
        with patch("app.crypto._get_fernet") as mock_get:
            mock_fernet = type("MockFernet", (), {})()
            mock_fernet.encrypt = lambda x: b"encrypted"
            mock_get.return_value = mock_fernet

            result = encrypt_webhook_secret("my-secret")
            assert result == "v1:encrypted"

    def test_decrypt_returns_string(self):
        with patch("app.crypto._get_fernet") as mock_get:
            mock_fernet = type("MockFernet", (), {})()
            mock_fernet.decrypt = lambda x: b"my-secret"
            mock_get.return_value = mock_fernet

            result = decrypt_webhook_secret("encrypted")
            assert result == "my-secret"

    def test_none_plaintext_returns_none(self):
        assert encrypt_webhook_secret(None) is None

    def test_none_ciphertext_returns_none(self):
        assert decrypt_webhook_secret(None) is None

    def test_fallback_prefix_on_encrypt_when_no_key(self):
        with patch("app.crypto.settings") as mock_settings:
            mock_settings.ENCRYPTION_KEY = ""
            result = encrypt_webhook_secret("my-secret")
            assert result == "safe_plain:my-secret"

    def test_fallback_prefix_stripped_on_decrypt(self):
        result = decrypt_webhook_secret("safe_plain:my-secret")
        assert result == "my-secret"

    def test_raw_ciphertext_returned_when_no_key(self):
        with patch("app.crypto.settings") as mock_settings:
            mock_settings.ENCRYPTION_KEY = ""
            result = decrypt_webhook_secret("some-ciphertext")
            assert result == "some-ciphertext"

    def test_roundtrip_with_fernet(self):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode("utf-8")

        with patch("app.crypto.settings") as mock_settings:
            mock_settings.ENCRYPTION_KEY = key
            mock_settings.ENVIRONMENT = "development"

            # Force re-creation of fernet instance
            import app.crypto as crypto
            crypto._fernet = None

            plaintext = "super-secret-webhook-key"
            encrypted = encrypt_webhook_secret(plaintext)
            assert encrypted != plaintext
            assert encrypted.startswith("v1:gAAAAAB")

            decrypted = decrypt_webhook_secret(encrypted)
            assert decrypted == plaintext

    def test_derive_key_from_raw_string(self):
        key = _derive_key("my-secret-key")
        assert key is not None
        assert len(key) == 44  # base64-encoded 32 bytes

    def test_derive_key_from_base64_prefix(self):
        # 32-byte base64url-encoded key
        b64_key = base64.urlsafe_b64encode(b"a" * 32).decode("utf-8")
        key = _derive_key(f"base64:{b64_key}")
        assert key is not None
        assert len(key) == 44

    def test_derive_key_empty_returns_none(self):
        assert _derive_key("") is None
