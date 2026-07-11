"""Application configuration loaded from environment variables.

Uses ``pydantic-settings`` to read values from the process environment and
an optional ``.env`` file. All required variables are validated at import
time so the application fails fast if secrets are missing.
"""

from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


class Settings(BaseSettings):
    """SafeRoute API runtime settings.

    Attributes:
        SUPABASE_URL: Supabase project URL.
        SUPABASE_KEY: Supabase anon / public key for client-side queries.
        SUPABASE_SERVICE_ROLE_KEY: Supabase service-role key for server-side
            operations that bypass Row Level Security.
        WEBHOOK_SECRET: Shared secret used for webhook signature verification.
        API_KEY_SALT: Salt used for HMAC hashing of API keys.
        RETRY_ENDPOINT_SECRET: Shared secret for the internal retry endpoint.
        FRONTEND_URL: Frontend origin for CORS and OAuth redirects.
        ENVIRONMENT: Deployment environment. Affects CORS, logging, and
            error detail. Defaults to ``production`` (fail-closed) so a
            misconfigured deployment never silently runs in an insecure
            development mode. Set explicitly to ``development`` for local
            work.
        TRUSTED_PROXIES: Comma-separated IPs of reverse proxies / CDNs whose
            ``X-Forwarded-For`` header should be trusted for client-IP
            extraction (per-IP rate limiting). Required when fronted by a
            CDN; empty means the direct peer IP is used.
        ALLOWED_HOSTS: Comma-separated Host header values permitted by
            TrustedHostMiddleware in production.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    WEBHOOK_SECRET: str = ""
    API_KEY_SALT: str
    RETRY_ENDPOINT_SECRET: str = ""
    ENCRYPTION_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "production"
    TRUSTED_PROXIES: str = ""
    ALLOWED_HOSTS: str = ""
    RETENTION_DAYS: int = 30

    @property
    def is_production(self) -> bool:
        """Return ``True`` if the app is running in production mode.

        Returns:
            ``True`` when ``ENVIRONMENT`` equals ``"production"``.
        """
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Return ``True`` if the app is running in local development."""
        return self.ENVIRONMENT == "development"

    def get_allowed_hosts(self) -> list[str]:
        """Return the list of allowed hosts for TrustedHostMiddleware.

        In production, respects the ``ALLOWED_HOSTS`` setting.
        In development, allows all hosts.
        """
        if self.is_production:
            if not self.ALLOWED_HOSTS.strip():
                raise ValueError("ALLOWED_HOSTS must be set in production")
            return [
                host.strip() for host in self.ALLOWED_HOSTS.split(",") if host.strip()
            ]
        return ["*"]

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Ensure critical security settings are configured in production.

        ``ENCRYPTION_KEY`` is only *required* in production. Outside production
        (development, testing, staging) a missing key is tolerated: the crypto
        layer falls back to storing webhook secrets with the ``safe_plain:``
        prefix rather than failing at import time. This keeps CI and non-prod
        deploys runnable while still failing closed where it matters most.
        """
        if self.is_production:
            if not self.ALLOWED_HOSTS.strip():
                raise ValueError("ALLOWED_HOSTS must be set in production")
            if not self.ENCRYPTION_KEY.strip():
                raise ValueError("ENCRYPTION_KEY must be set in production")
        return self


settings = Settings()  # type: ignore[call-arg]
