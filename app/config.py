"""Application configuration loaded from environment variables.

Uses ``pydantic-settings`` to read values from the process environment and
an optional ``.env`` file. All required variables are validated at import
time so the application fails fast if secrets are missing.
"""

from __future__ import annotations
import warnings
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
    DATABASE_URL: str
    WEBHOOK_SECRET: str = ""
    API_KEY_SALT: str
    RETRY_ENDPOINT_SECRET: str = ""
    ENCRYPTION_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "production"
    TRUSTED_PROXIES: str = ""
    ALLOWED_HOSTS: str = ""
    RETENTION_DAYS: int = 30
    OUTBOUND_HEALTH_CHECK_URL: str = "https://www.google.com/generate_204"
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    DEFAULT_RATE_LIMIT: int = 30
    FORWARD_TIMEOUT_SECONDS: float = 10.0
    MAX_LOG_BODY_BYTES: int = 10_000
    MAX_RETRIES: int = 3
    RETRY_BATCH_SIZE: int = 100
    RETRY_CLAIM_STALE_SECONDS: int = 300
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@saferoute.dev"
    EMAIL_REPLY_TO: str = ""
    TURNSTILE_SECRET_KEY: str = ""

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
            if not self.ENCRYPTION_KEY.strip() or len(self.ENCRYPTION_KEY) < 32:
                raise ValueError(
                    "ENCRYPTION_KEY must be a strong secret (at least 32 chars) in prod"
                )
            if not self.API_KEY_SALT.strip() or len(self.API_KEY_SALT) < 16:
                raise ValueError(
                    "API_KEY_SALT must be a strong secret (at least 16 chars) in prod"
                )
            if self.WEBHOOK_SECRET and len(self.WEBHOOK_SECRET) < 32:
                raise ValueError(
                    "WEBHOOK_SECRET must be at least 32 chars in production"
                )
            if self.RETRY_ENDPOINT_SECRET and len(self.RETRY_ENDPOINT_SECRET) < 32:
                raise ValueError(
                    "RETRY_ENDPOINT_SECRET must be at least 32 chars in production"
                )
            if self.RESEND_API_KEY and len(self.RESEND_API_KEY) < 16:
                raise ValueError(
                    "RESEND_API_KEY must be at least 16 chars in production"
                )
            if self.TURNSTILE_SECRET_KEY and len(self.TURNSTILE_SECRET_KEY) < 16:
                raise ValueError(
                    "TURNSTILE_SECRET_KEY must be at least 16 chars in production"
                )
        elif not self.ENCRYPTION_KEY.strip():

            warnings.warn(
                "Running without ENCRYPTION_KEY. "
                "Webhook secrets will be stored in plain text.",
                RuntimeWarning,
                stacklevel=2,
            )
        return self


settings = Settings()  # type: ignore[call-arg]
