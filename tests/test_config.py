"""Tests for application configuration and secure-by-default behaviour."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def _base_env(monkeypatch):
    """Set the minimal required settings and clear environment-specific ones."""
    for var in (
        "ENVIRONMENT",
        "ENCRYPTION_KEY",
        "ALLOWED_HOSTS",
        "WEBHOOK_SECRET",
        "RETRY_ENDPOINT_SECRET",
        "TRUSTED_PROXIES",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("API_KEY_SALT", "this-is-a-very-strong-salt-key-that-is-at-least-16-chars")


def test_default_environment_is_production(monkeypatch):
    """A missing ENVIRONMENT must default to production (fail-closed) and
    therefore still enforce production requirements rather than silently
    running in an insecure development mode."""
    _base_env(monkeypatch)
    # No ALLOWED_HOSTS/ENCRYPTION_KEY -> production defaults refuse to start.
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("ENCRYPTION_KEY", "this-is-a-very-strong-secret-key-that-is-at-least-32-chars")
    settings = Settings(_env_file=None)
    assert settings.ENVIRONMENT == "production"


def test_production_requires_encryption_key_and_allowed_hosts(monkeypatch):
    """Production must refuse to start without ENCRYPTION_KEY/ALLOWED_HOSTS."""
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    # No ENCRYPTION_KEY -> should fail validation.
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    monkeypatch.setenv("ENCRYPTION_KEY", "this-is-a-very-strong-secret-key-that-is-at-least-32-chars")
    settings = Settings(_env_file=None)
    assert settings.ENVIRONMENT == "production"
    assert settings.ENCRYPTION_KEY == "this-is-a-very-strong-secret-key-that-is-at-least-32-chars"


def test_non_production_allows_missing_encryption_key(monkeypatch):
    """testing/staging must remain runnable without ENCRYPTION_KEY (graceful
    safe_plain fallback), unlike the old behaviour that crashed CI."""
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "testing")
    settings = Settings(_env_file=None)
    assert settings.ENCRYPTION_KEY == ""
    assert settings.is_production is False


def test_development_allows_missing_encryption_key(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "development")
    settings = Settings(_env_file=None)
    assert settings.ENVIRONMENT == "development"
    assert settings.ENCRYPTION_KEY == ""
